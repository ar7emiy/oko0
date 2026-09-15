"""Gemini transport: JSON-schema constrained output + embeddings, with a disk
cache keyed by (model, prompt_hash) and a deterministic OFFLINE fallback.

- ONLINE (API key present): calls the real Gemini API. Structured extraction /
  adjudication / query-planning use Gemini's JSON-schema constrained output.
  Embeddings use EMBED_MODEL. Responses are cached to store/genai_cache keyed by
  sha256(model + task + prompt) so re-runs are cheap and deterministic.
- OFFLINE (no key, or GENAI_MODE=offline): generate_json() delegates to an
  ``offline_handler`` thunk supplied by each caller (deterministic heuristics
  live next to the online prompt, in extraction.py / resolution.py / app.py);
  embed() returns a deterministic hashing embedding. This lets the ENTIRE
  pipeline + every research invariant run without network or credentials.

Only GENAI_MODEL / EMBED_MODEL from config name a model; this module reads them
from settings, never hardcodes.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import random
import threading
import time
from collections.abc import Callable

import numpy as np

from .settings import CFG, Paths, api_key, genai_mode

_lock = threading.Lock()
_client = None  # lazily-initialized google-genai client


def _prompt_hash(model: str, task: str, prompt: str, extra: str = "") -> str:
    return hashlib.sha256(f"{model}\x00{task}\x00{prompt}\x00{extra}".encode()).hexdigest()


def _cache_path(h: str):
    Paths.genai_cache.mkdir(parents=True, exist_ok=True)
    return Paths.genai_cache / f"{h}.json"


def _cache_get(h: str):
    p = _cache_path(h)
    if CFG.GENAI_CACHE_ENABLED and p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _cache_put(h: str, value) -> None:
    if CFG.GENAI_CACHE_ENABLED:
        _cache_path(h).write_text(json.dumps(value), encoding="utf-8")


def _get_client():
    global _client
    with _lock:
        if _client is None:
            from google import genai  # lazy import; only needed online
            _client = genai.Client(api_key=api_key())
        return _client


# ---------------------------------------------------------------------------
# Structured generation
# ---------------------------------------------------------------------------
def model_for(task: str) -> str:
    """Which Gemini model serves this task.

    Per-task routing exists because the lanes differ by orders of magnitude in
    call volume and by a lot in how much judgement they need. See
    CFG.GENAI_MODEL_BY_TASK for which lanes may be downgraded and which are
    pinned to a model a quality number was measured on.
    """
    return getattr(CFG, "GENAI_MODEL_BY_TASK", {}).get(task, CFG.GENAI_MODEL)


def generate_json(
    prompt: str,
    schema: dict,
    *,
    task: str,
    offline_handler: Callable[[], dict] | None = None,
    system: str | None = None,
) -> dict:
    """Return a dict conforming to `schema`.

    Online: Gemini constrained decode (response_mime_type=application/json,
    response_schema=schema), cached. Offline: call offline_handler().
    """
    if genai_mode() == "offline":
        if offline_handler is None:
            raise RuntimeError(f"offline mode requires an offline_handler for task={task}")
        return offline_handler()

    model = model_for(task)
    # The model is part of the cache key, so switching a lane's model does not
    # silently serve answers the old model produced.
    h = _prompt_hash(model, task, prompt, system or "")
    cached = _cache_get(h)
    if cached is not None:
        return cached

    from google.genai import types
    client = _get_client()
    contents = prompt if system is None else f"{system}\n\n{prompt}"
    last_err = None
    for attempt in range(CFG.GENAI_MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
                ),
            )
            data = json.loads(resp.text)
            _cache_put(h, data)
            return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            # Backoff, because the retries were previously back-to-back with no
            # delay at all -- which means four attempts inside a few
            # milliseconds, all failing for the same transient reason. Measured
            # consequence: one `[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]` killed a
            # 60-document extraction eight minutes in, discarding the work.
            # Transient TLS resets and 429s are the common case on this path and
            # they clear in seconds, so an instant retry is the one strategy
            # guaranteed not to help.
            if attempt < CFG.GENAI_MAX_RETRIES - 1:
                time.sleep(min(8.0, 0.5 * 2 ** attempt) * (1 + random.random()))
    raise RuntimeError(f"Gemini generate_json failed for task={task}: {last_err}")


def generate_json_batch(
    jobs: list[dict],
    schema: dict,
    *,
    task: str,
    max_workers: int | None = None,
) -> list[dict]:
    """Batch structured generation. Each job = {'prompt': str, 'offline_handler': fn, 'system': str?}.
    Offline jobs run inline (deterministic). Online jobs run in a thread pool.
    """
    if genai_mode() == "offline":
        return [j["offline_handler"]() for j in jobs]
    workers = max_workers or CFG.GENAI_MAX_WORKERS
    results: list[dict | None] = [None] * len(jobs)

    def _run(i: int):
        j = jobs[i]
        results[i] = generate_json(
            j["prompt"], schema, task=task,
            offline_handler=j.get("offline_handler"), system=j.get("system"),
        )

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_run, range(len(jobs))))
    return results  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
def _offline_embedding(text: str, dim: int) -> np.ndarray:
    """Deterministic hashing embedding: char 3-5 grams hashed into `dim` buckets.

    Identical text -> identical vector; near-duplicate text -> high cosine.
    Not semantic, but sufficient to exercise the VectorStore interface and to
    give the resolution embedding pass a reproducible, meaningful signal offline.
    """
    v = np.zeros(dim, dtype=np.float32)
    t = " ".join((text or "").lower().split())
    if not t:
        v[0] = 1.0
        return v
    for n in (3, 4, 5):
        for i in range(len(t) - n + 1):
            g = t[i : i + n]
            hh = int.from_bytes(hashlib.md5(g.encode()).digest()[:8], "little")
            v[hh % dim] += 1.0
    nrm = np.linalg.norm(v)
    return v / nrm if nrm > 0 else v


def embed(texts: list[str]) -> np.ndarray:
    """Return an (n, EMBED_DIM) float32 L2-normalized matrix."""
    dim = CFG.EMBED_DIM
    if genai_mode() == "offline":
        return np.vstack([_offline_embedding(t, dim) for t in texts]).astype(np.float32)

    out = np.zeros((len(texts), dim), dtype=np.float32)
    todo = []
    for i, t in enumerate(texts):
        h = _prompt_hash(CFG.EMBED_MODEL, "embed", t)
        c = _cache_get(h)
        if c is not None:
            out[i] = np.asarray(c, dtype=np.float32)
        else:
            todo.append((i, t, h))
    if todo:
        client = _get_client()
        # Thread pool, mirroring generate_many. This used to be a serial loop,
        # which was tolerable when the only caller embedded chunks. The
        # embedding blocking lane embeds every MENTION, so at corpus scale a
        # serial loop is tens of thousands of sequential round trips.
        errors: list[Exception] = []

        def _one(job) -> None:
            i, t, h = job
            last_err = None
            for _ in range(CFG.GENAI_MAX_RETRIES):
                try:
                    r = client.models.embed_content(model=CFG.EMBED_MODEL, contents=t)
                    vec = np.asarray(r.embeddings[0].values, dtype=np.float32)
                    n = np.linalg.norm(vec)
                    vec = vec / n if n > 0 else vec
                    if vec.shape[0] != dim:  # pad/truncate defensively
                        z = np.zeros(dim, dtype=np.float32)
                        z[: min(dim, vec.shape[0])] = vec[:dim]
                        vec = z
                    out[i] = vec
                    _cache_put(h, vec.tolist())
                    return
                except Exception as e:  # noqa: BLE001
                    last_err = e
            errors.append(last_err)

        with cf.ThreadPoolExecutor(max_workers=CFG.GENAI_MAX_WORKERS) as ex:
            list(ex.map(_one, todo))
        if errors:
            raise RuntimeError(
                f"Gemini embed failed for {len(errors)} of {len(todo)} texts; "
                f"first error: {errors[0]}")
    return out
