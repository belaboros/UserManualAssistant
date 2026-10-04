import pytest

from uma.corpus.ingest import ingest, load_manual_meta, parse_manual


def test_ingest_mini_corpus(mini_corpus, tmp_store, embedder):
    r = ingest(mini_corpus, tmp_store, embedder)
    assert r.manuals == 2 and r.sections == len(tmp_store.sections()) and r.chunks >= r.sections
    assert {m.meta.id for m in tmp_store.manuals()} == {"alpha", "beta"}
    assert r.skipped == []


def test_meta_defaults(mini_corpus):
    a = load_manual_meta(mini_corpus / "alpha")
    assert a.id == "alpha" and a.visibility == "internal" and a.base_url is None
    assert load_manual_meta(mini_corpus / "beta").visibility == "external"


def test_folder_without_yaml_skipped(mini_corpus, tmp_store, embedder):
    (mini_corpus / "gamma").mkdir()
    (mini_corpus / "gamma" / "x.md").write_text("# X\ntext\n")
    r = ingest(mini_corpus, tmp_store, embedder)
    assert r.skipped == ["gamma"] and r.manuals == 2


def test_missing_title_raises(tmp_path):
    (tmp_path / "manual.yaml").write_text("owner: me\n")
    with pytest.raises(ValueError, match="manual.yaml"):
        load_manual_meta(tmp_path)


def test_reingest_replaces(mini_corpus, tmp_store, embedder):
    r1 = ingest(mini_corpus, tmp_store, embedder)
    r2 = ingest(mini_corpus, tmp_store, embedder)
    assert (r1.manuals, r1.sections, r1.chunks) == (r2.manuals, r2.sections, r2.chunks)
    assert len(tmp_store.sections()) == r2.sections and len(tmp_store.chunk_matrix()[0]) == r2.chunks


def test_parse_manual_recurses_sorted_with_continuing_positions(tmp_path):
    f = tmp_path / "m"
    (f / "sub").mkdir(parents=True)
    (f / "manual.yaml").write_text("title: M\n")
    (f / "b.md").write_text("# B\nb\n")
    (f / "sub" / "a.html").write_text("<h1>A</h1><p>a</p>")
    (f / "notes.txt").write_text("ignored")
    secs = parse_manual(f, load_manual_meta(f))
    assert [s.doc_path for s in secs] == ["b.md", "sub/a.html"]
    assert [s.position for s in secs] == [0, 1]
