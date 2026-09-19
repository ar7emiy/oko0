"""Layer 1e: pass-2 verification sweep (differential audit).

After the union pass, re-read the raw text and find every token that is NOT
covered by any extracted span. Those "unmapped" tokens are the candidates the
first pass drifted past. Each is adjudicated -- online by feeding the extracted
JSON back to Gemini alongside the source text (forcing a differential audit),
offline by a deterministic rule -- and genuine misses are promoted into the span
set with provenance `sweep`.

This is what converts "the LLM usually catches things" into a measurable,
auditable claim: after the sweep, any remaining uncovered token is either
explicitly classified as a non-entity or reported.
"""
from __future__ import annotations

import re

from . import contracts, coref, gazetteers, genai, ner_ensemble
from .ner_ensemble import SpanCandidate
from .settings import CFG

# tokens that are structural/boilerplate, not candidate entities
_NOISE = {
    "the", "and", "for", "with", "from", "sent", "subject", "please", "advise",
    "claim", "note", "status", "per", "our", "call", "attaching", "updated",
    "demand", "client", "available", "next", "week", "have", "not", "received",
    "records", "yet", "kindly", "expedite", "confidentiality", "notice", "this",
    "email", "any", "attachments", "are", "sole", "use", "intended", "recipient",
    "may", "contain", "privileged", "information", "you", "notify", "sender",
    "delete", "message", "direct", "earlier", "prior", "same", "above", "denies",
    "alleges", "ongoing", "pain", "spoke", "clmt", "atty", "poa", "corr", "coverage",
    "states", "mail", "returned", "undeliverable", "will", "confirm", "new", "addr",
    "tx", "dr", "re", "following", "suspect", "shop", "inflating", "parts", "file",
    "wrong", "correct", "listed", "birth", "date", "phone", "address", "mailing",
    "contact", "provider", "physician", "treating", "counsel", "attorney", "claimant",
    "name", "nm", "num", "tel", "ph", "dob", "birthdate", "npi", "tin", "email",
}

# [ \t] not \s: a candidate span must never cross a newline (see ner_ensemble)
_CANDIDATE_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z'’\-]{2,}(?:[ \t]+[A-Z][a-zA-Z'’\-]{2,})*|\d[\w\-./]{2,})\b"
)


def uncovered_candidates(text: str, spans: list[SpanCandidate],
                         base_offset: int = 0) -> list[tuple[int, int, str]]:
    """Find candidate tokens in `text` not covered by any extracted span."""
    n = len(text)
    covered = bytearray(n)
    for s in spans:
        a = max(0, s.start - base_offset)
        b = min(n, s.end - base_offset)
        for i in range(a, b):
            covered[i] = 1

    out = []
    for m in _CANDIDATE_RE.finditer(text):
        s, e = m.start(), m.end()
        if any(covered[i] for i in range(s, e)):
            continue
        surface = m.group(0)
        if len(surface) < CFG.SWEEP_MIN_TOKEN_LEN:
            continue
        if coref.is_anaphor(surface):
            continue
        words = [w for w in re.split(r"\s+", surface) if w]
        if all(w.lower().strip(".,") in _NOISE for w in words):
            continue
        out.append((base_offset + s, base_offset + e, surface))
        if len(out) >= CFG.SWEEP_MAX_CANDIDATES_PER_CHUNK:
            break
    return out


def _sweep_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "missed": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "start": {"type": "integer"},
                        "end": {"type": "integer"},
                        "label": {"type": "string", "enum": list(CFG.NER_LABELS)},
                        "reason": {"type": "string"},
                    },
                    "required": ["text", "start", "end", "label"],
                },
            }
        },
        "required": ["missed"],
    }


def _offline_verdicts(candidates, text, base_offset):
    """Deterministic differential audit.

    Promote an unmapped token when it looks like a real entity: a multi-word
    capitalized name, a title-led name, a validated structured code, or a
    capitalized token sitting next to a role cue.
    """
    promoted = []
    for (s, e, surface) in candidates:
        rel_s = s - base_offset
        left = text[max(0, rel_s - 40):rel_s]
        label = None
        words = surface.split()
        gaz = gazetteers.scan_valid(surface)
        if gaz and gaz[0].end - gaz[0].start == len(surface):
            label = gaz[0].label
        elif len(words) >= 2 and all(w[:1].isupper() for w in words):
            label = gazetteers.role_from_context(left) or "person"
        elif surface.lower().startswith("dr"):
            label = "medical_provider"
        elif gazetteers.role_from_context(left) and surface[:1].isupper():
            label = gazetteers.role_from_context(left)
        if label:
            promoted.append({"text": surface, "start": s, "end": e,
                             "label": label, "reason": "unmapped token promoted by sweep"})
    return {"missed": promoted}


def sweep_chunk(chunk, spans: list[SpanCandidate]) -> list[SpanCandidate]:
    """Run the differential audit for one chunk; return newly-found spans."""
    if not CFG.SWEEP_ENABLED:
        return []
    cands = uncovered_candidates(chunk.text, spans, chunk.char_start)
    if not cands:
        return []

    extracted_summary = [{"text": s.text, "label": s.label,
                          "start": s.start - chunk.char_start,
                          "end": s.end - chunk.char_start} for s in spans]
    prompt = (
        "DIFFERENTIAL AUDIT. Below is a claim-note chunk and the entities already "
        "extracted from it. Identify entities present in the text that are MISSING "
        "from the extraction list -- especially low-salience details: secondary "
        "providers, paralegals, codes, dates, amounts. Return offsets within the "
        "chunk. Never return pronouns or vague descriptors.\n\n"
        f"CHUNK:\n<<<\n{chunk.text}\n>>>\n\n"
        f"ALREADY EXTRACTED:\n{extracted_summary}\n\n"
        f"UNMAPPED CANDIDATE TOKENS:\n{[c[2] for c in cands]}"
    )

    def offline():
        return _offline_verdicts(cands, chunk.text, chunk.char_start)

    data = genai.generate_json(prompt, _sweep_schema(), task="sweep",
                               offline_handler=offline)
    # LOCATE each surface in the chunk instead of trusting the model's offsets.
    #
    # Two defects are being replaced here. The first is the one ner_ensemble
    # had: `start`/`end` came from the model, were clamped so nothing crashed,
    # and the surface was taken from the model's own `text` field with no check
    # that the span contained it. A model cannot count characters.
    #
    # The second was local and sharper. The line
    #     if s < chunk.char_start: s += chunk.char_start
    # tried to GUESS whether an offset was chunk-relative or absolute. For any
    # chunk after the first, a chunk-relative offset larger than char_start
    # reads as absolute and is left unshifted -- so the further into a document
    # a span sat, the more likely it was silently misplaced.
    out = []
    for m in data.get("missed", []):
        surface = (m.get("text") or "").strip()
        if not surface or coref.is_anaphor(surface):
            continue
        try:
            raw = int(m.get("start", 0))
        except (TypeError, ValueError):
            raw = 0
        # Treat the number only as a hint, and normalise it into chunk space
        # rather than deciding what it "meant".
        hint = raw - chunk.char_start if raw >= chunk.char_start else raw
        pos = ner_ensemble._locate(chunk.text, surface,
                                   max(0, min(hint, len(chunk.text))))
        if pos < 0:
            continue                     # not in this chunk: not a mention here
        s = chunk.char_start + pos
        out.append(SpanCandidate(start=s, end=s + len(surface), text=surface,
                                 label=m.get("label", "person"),
                                 extractors={"sweep"}, score=0.6,
                                 description=m.get("reason", ""),
                                 chunk_ids={chunk.chunk_id}))
    return out


def residual_report(text: str, spans: list[SpanCandidate]) -> dict:
    """After the sweep, what is still unmapped? (honesty instrument)"""
    left = uncovered_candidates(text, spans, 0)
    return {"n_residual_candidates": len(left),
            "residual_sample": [t for (_, _, t) in left[:15]]}
