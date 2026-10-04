"""Hybrid search: FTS5 BM25 + vector similarity fused with reciprocal rank fusion."""

from dataclasses import dataclass

import numpy as np

from uma.corpus.models import Chunk, Section
from uma.corpus.store import CorpusStore
from uma.embedding import Embedder

RRF_K = 60


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    section: Section
    score: float  # RRF score, higher is better


def _vector_ranking(
    store: CorpusStore, embedder: Embedder, query: str, candidates: int, manual_id: str | None
) -> list[str]:
    ids, matrix = store.chunk_matrix()
    if not ids:
        return []
    q = embedder.embed([query])[0]
    if not np.any(q):
        return []
    order = np.argsort(-(matrix @ q), kind="stable")
    allowed = None if manual_id is None else store.chunk_ids_for_manual(manual_id)
    out: list[str] = []
    for i in order:
        if allowed is not None and ids[i] not in allowed:
            continue
        out.append(ids[i])
        if len(out) >= candidates:
            break
    return out


def hybrid_search(
    store: CorpusStore,
    embedder: Embedder,
    query: str,
    *,
    k: int = 8,
    manual_id: str | None = None,
    candidates: int = 30,
) -> list[SearchHit]:
    if not query.strip():
        return []
    fts_ids = [cid for cid, _ in store.fts_search(query, candidates, manual_id)]
    vec_ids = _vector_ranking(store, embedder, query, candidates, manual_id)
    scores: dict[str, float] = {}
    for ranking in (fts_ids, vec_ids):
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1 / (RRF_K + rank)
    hits: list[SearchHit] = []
    for cid, score in sorted(scores.items(), key=lambda kv: -kv[1])[:k]:
        chunk = store.chunk(cid)
        section = store.section(chunk.section_id)
        if section is not None:
            hits.append(SearchHit(chunk, section, score))
    return hits


def ensure_manual_coverage(
    ranked: list[SearchHit], k: int, min_ratio: float = 0.5
) -> list[SearchHit]:
    out = ranked[:k]
    if not ranked:
        return out
    threshold = min_ratio * ranked[0].score
    seen = {h.chunk.manual_id for h in out}
    for h in ranked[k:]:  # ranked is score-descending, so first seen is a manual's best
        m = h.chunk.manual_id
        if m not in seen:
            seen.add(m)
            if h.score >= threshold:
                out.append(h)
    return out


def retrieve_for_rag(
    store: CorpusStore, embedder: Embedder, query: str, k: int
) -> list[SearchHit]:
    return ensure_manual_coverage(hybrid_search(store, embedder, query, k=10_000), k)
