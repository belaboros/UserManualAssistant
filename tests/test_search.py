import numpy as np

from uma.corpus.models import Chunk, ManualMeta, Section
from uma.search import SearchHit, ensure_manual_coverage, hybrid_search, retrieve_for_rag


class StubEmbedder:
    """Maps known query strings to fixed vectors; anything else to zeros."""

    dim = 4

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts):
        return np.array([self.vectors.get(t, [0, 0, 0, 0]) for t in texts], dtype=np.float32)


def _add(store, manual_id, n, text, vec):
    store.add_manual(ManualMeta(manual_id, manual_id, "o", "internal", None))
    sec = Section(f"{manual_id}-s{n}", manual_id, "d.md", ("H",), "h", text, n, None)
    store.add_sections([sec])
    store.add_chunks(
        [Chunk(f"{manual_id}-c{n}", sec.id, manual_id, text, n)],
        np.array([vec], dtype=np.float32),
    )


def _corpus(store):
    _add(store, "alpha", 0, "the zebra protocol requires a handshake", [0, 0, 1, 0])
    _add(store, "alpha", 1, "unrelated filler about cables", [0, 0, 0, 1])
    _add(store, "beta", 0, "pairing flow with the mobile app", [1, 0, 0, 0])
    _add(store, "beta", 1, "more filler about lenses", [0, 1, 0, 0])


def hit(manual_id, score):
    c = Chunk(f"{manual_id}-{score}", "s", manual_id, "t", 0)
    s = Section("s", manual_id, "d", ("H",), "a", "t", 0, None)
    return SearchHit(c, s, score)


def test_keyword_and_semantic_both_contribute(tmp_store):
    _corpus(tmp_store)
    emb = StubEmbedder({"zebra connect": [1, 0, 0, 0]})  # semantic -> beta pairing chunk
    hits = hybrid_search(tmp_store, emb, "zebra connect", k=2)
    ids = {h.chunk.id for h in hits}
    assert "alpha-c0" in ids  # exact term only
    assert "beta-c0" in ids  # vector only
    assert all(h.section.id == h.chunk.section_id for h in hits)


def test_manual_filter(tmp_store):
    _corpus(tmp_store)
    emb = StubEmbedder({"zebra connect": [0, 0, 1, 0]})
    hits = hybrid_search(tmp_store, emb, "zebra connect", k=5, manual_id="beta")
    assert hits
    assert all(h.chunk.manual_id == "beta" for h in hits)


def test_rrf_scores_descending(tmp_store):
    _corpus(tmp_store)
    emb = StubEmbedder({"zebra": [0, 0, 1, 0]})
    hits = hybrid_search(tmp_store, emb, "zebra", k=10)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    # top chunk is rank 1 in both lists: 1/61 + 1/61
    assert hits[0].chunk.id == "alpha-c0"
    assert abs(hits[0].score - 2 / 61) < 1e-9


def test_coverage_adds_missing_manual():
    ranked = [hit("a", .03), hit("a", .029), hit("a", .028), hit("b", .02), hit("c", .01)]
    out = ensure_manual_coverage(ranked, k=2)
    assert [h.chunk.manual_id for h in out] == ["a", "a", "b"]  # c's .01 < .5 * .03


def test_empty_query_returns_empty(tmp_store, embedder):
    _corpus(tmp_store)
    assert hybrid_search(tmp_store, embedder, "", k=5) == []
    assert hybrid_search(tmp_store, embedder, "   ", k=5) == []


def test_empty_store_returns_empty(tmp_store, embedder):
    assert hybrid_search(tmp_store, embedder, "anything", k=5) == []


def test_retrieve_for_rag_applies_coverage(tmp_store):
    _corpus(tmp_store)
    emb = StubEmbedder({"zebra": [0, 0, 1, 0]})
    out = retrieve_for_rag(tmp_store, emb, "zebra", k=1)
    assert out[0].chunk.id == "alpha-c0"
