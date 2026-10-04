from uma.corpus.chunking import chunk_sections
from uma.corpus.models import ManualMeta, Section


def _meta(id="m"):
    return ManualMeta(id=id, title=f"Manual {id}", owner="o", visibility="internal", base_url=None)


def _sec(manual_id, n, text):
    return Section(id=f"{manual_id}:d:s{n}", manual_id=manual_id, doc_path="d.md",
                   heading_path=("H", f"S{n}"), anchor=f"s{n}", text=text, position=n, source_url=None)


def _fill(store, embedder, sections, metas):
    for m in metas:
        store.add_manual(m)
    store.add_sections(sections)
    chunks = chunk_sections(sections)
    store.add_chunks(chunks, embedder.embed([c.text for c in chunks]))
    return chunks


def test_roundtrip_and_fts(tmp_store, embedder):
    secs = [_sec("m", 1, "Restart the router now."), _sec("m", 0, "Intro about cables.")]
    chunks = _fill(tmp_store, embedder, secs, [_meta()])
    assert [s.position for s in tmp_store.sections()] == [0, 1]
    assert tmp_store.section("m:d:s1") == secs[0]
    assert tmp_store.section("nope") is None
    assert tmp_store.chunk(chunks[0].id) == chunks[0]
    ids, mat = tmp_store.chunk_matrix()
    assert len(ids) == 2 and mat.shape == (2, embedder.dim) and mat.dtype.name == "float32"
    hits = tmp_store.fts_search("router", limit=5)
    assert [h[0] for h in hits] == ["m:d:s1#0"]
    assert tmp_store.fts_search("router", limit=5, manual_id="other") == []
    assert tmp_store.manuals()[0].section_count == 2


def test_manuals_ordered_by_id_with_counts(tmp_store, embedder):
    secs = [_sec("b", 0, "bee"), _sec("a", 0, "ay"), _sec("a", 1, "ay two")]
    _fill(tmp_store, embedder, secs, [_meta("b"), _meta("a")])
    recs = tmp_store.manuals()
    assert [r.meta.id for r in recs] == ["a", "b"]
    assert [r.section_count for r in recs] == [2, 1]
    assert all(r.token_count is None for r in recs)


def test_fts_search_tolerates_special_characters(tmp_store, embedder):
    chunks = _fill(tmp_store, embedder, [_sec("m", 0, "Reset the C++ SDK: hold (button) 10 s")], [_meta()])
    chunk_id = chunks[0].id
    for q in ['"', "C++", "reset*", "hold: (button)", "AND", "-x", "what's up?"]:
        tmp_store.fts_search(q, limit=5)
    assert tmp_store.fts_search("reset C++ sdk?", limit=5)[0][0] == chunk_id


def test_reset_clears(tmp_store, embedder):
    _fill(tmp_store, embedder, [_sec("m", 0, "hello world")], [_meta()])
    tmp_store.set_token_count(None, 5)
    assert not tmp_store.is_empty()
    tmp_store.reset()
    assert tmp_store.is_empty() and tmp_store.manuals() == [] and tmp_store.sections() == []
    assert tmp_store.fts_search("hello", limit=5) == [] and tmp_store.corpus_token_count() is None


def test_token_count_roundtrip(tmp_store):
    assert tmp_store.corpus_token_count() is None and tmp_store.is_empty()
    tmp_store.add_manual(_meta())
    tmp_store.set_token_count(None, 123)
    tmp_store.set_token_count("m", 45)
    assert tmp_store.corpus_token_count() == 123
    assert tmp_store.manuals()[0].token_count == 45
