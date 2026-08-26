"""Single VectorStore abstraction (HARD REQUIREMENT).

All vector operations in the system go through the abstract ``VectorStore``
interface. FAISS is a temporary stand-in for a managed vector store; a future
managed store is swapped in by implementing this same interface and nothing
else in the codebase changes.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from pathlib import Path

import faiss
import numpy as np
import pandas as pd


class VectorStore(ABC):
    """Abstract vector store.

    Contract (every implementation MUST honor):
      - upsert(ids, vectors, metadata): add/replace vectors keyed by string id,
        with a per-id metadata dict. Vectors are L2-normalized cosine vectors.
      - search(vector, k, filter_fn=None): return up to k (id, score) pairs in
        descending similarity. If filter_fn is given it is a predicate over a
        metadata dict; only ids whose metadata passes may be returned, and the
        result must still contain the true top-k *among the filtered set* (not a
        best-effort post-filter that can drop real matches).
      - persist() / load(): round-trip the index + metadata to/from disk.

    ---------------------------------------------------------------------------
    To swap in a managed store (e.g. AzureAISearchVectorStore) implement a
    subclass that:
      * upsert():   pushes each id's vector + metadata as a document to the
                    managed index (vector field + filterable metadata fields).
      * search():   issues a vector query with k = the requested k; translate
                    filter_fn into the store's native filter expression (the
                    filter must be applied server-side BEFORE nearest-neighbor
                    selection so recall over the filtered set is exact, mirroring
                    the IDSelector pre-filter used here). Return (id, score).
      * persist()/load(): no-ops or index-alias management, since the managed
                    store is durable server-side.
    The rest of the pipeline treats it identically; no other code changes.
    ---------------------------------------------------------------------------
    """

    @abstractmethod
    def upsert(self, ids: list[str], vectors: np.ndarray, metadata: list[dict]) -> None: ...

    @abstractmethod
    def search(self, vector: np.ndarray, k: int,
               filter_fn: Callable[[dict], bool] | None = None) -> list[tuple[str, float]]: ...

    @abstractmethod
    def persist(self) -> None: ...

    @abstractmethod
    def load(self) -> None: ...


class FaissVectorStore(VectorStore):
    """FAISS IndexFlatIP (exact inner-product = cosine on normalized vectors).

    IndexFlatIP is chosen deliberately: at POC scale exact search removes any
    ANN-recall confound from the resolution evaluation. Metadata filtering is
    emulated with a sidecar pandas DataFrame: filter to candidate integer ids
    first, then restrict the search with faiss.IDSelectorBatch so the returned
    top-k is exact over the filtered set (no enlarge-k-and-post-filter recall
    gamble).
    """

    def __init__(self, dim: int, index_path: Path, meta_path: Path):
        self.dim = dim
        self.index_path = Path(index_path)
        self.meta_path = Path(meta_path)
        self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        self._str2int: dict[str, int] = {}
        self._int2str: dict[int, str] = {}
        self._meta: dict[int, dict] = {}
        self._next_int = 0

    def _intern(self, sid: str) -> int:
        if sid in self._str2int:
            return self._str2int[sid]
        i = self._next_int
        self._next_int += 1
        self._str2int[sid] = i
        self._int2str[i] = sid
        return i

    def upsert(self, ids: list[str], vectors: np.ndarray, metadata: list[dict]) -> None:
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise ValueError(f"vectors must be (n,{self.dim}); got {vectors.shape}")
        int_ids = []
        for sid, meta in zip(ids, metadata):
            iid = self._intern(sid)
            # replace-if-exists: remove prior vector for this id
            try:
                self._index.remove_ids(np.array([iid], dtype=np.int64))
            except Exception:
                pass
            self._meta[iid] = dict(meta)
            int_ids.append(iid)
        self._index.add_with_ids(vectors, np.asarray(int_ids, dtype=np.int64))

    def search(self, vector: np.ndarray, k: int,
               filter_fn: Callable[[dict], bool] | None = None) -> list[tuple[str, float]]:
        q = np.ascontiguousarray(vector, dtype=np.float32).reshape(1, self.dim)
        if self._index.ntotal == 0:
            return []
        params = None
        if filter_fn is not None:
            allowed = [iid for iid, m in self._meta.items() if filter_fn(m)]
            if not allowed:
                return []
            sel = faiss.IDSelectorBatch(np.asarray(allowed, dtype=np.int64))
            params = faiss.SearchParameters()
            params.sel = sel
            kk = min(k, len(allowed))
        else:
            kk = min(k, self._index.ntotal)
        if params is not None:
            scores, idxs = self._index.search(q, kk, params=params)
        else:
            scores, idxs = self._index.search(q, kk)
        out = []
        for score, iid in zip(scores[0], idxs[0]):
            if iid == -1:
                continue
            out.append((self._int2str[int(iid)], float(score)))
        return out

    def persist(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_path))
        rows = [{"int_id": iid, "str_id": self._int2str[iid], "meta": json.dumps(self._meta.get(iid, {}))}
                for iid in self._int2str]
        pd.DataFrame(rows).to_parquet(self.meta_path, index=False)

    def load(self) -> None:
        self._index = faiss.read_index(str(self.index_path))
        df = pd.read_parquet(self.meta_path)
        self._str2int, self._int2str, self._meta = {}, {}, {}
        for _, r in df.iterrows():
            iid = int(r["int_id"])
            self._int2str[iid] = r["str_id"]
            self._str2int[r["str_id"]] = iid
            self._meta[iid] = json.loads(r["meta"])
        self._next_int = (max(self._int2str) + 1) if self._int2str else 0

    # convenience for the sidecar metadata DataFrame view
    def metadata_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{"str_id": self._int2str[i], **self._meta.get(i, {})} for i in self._int2str]
        )
