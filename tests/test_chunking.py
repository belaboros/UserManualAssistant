from uma.corpus.chunking import chunk_sections
from uma.corpus.models import Section


def _sec(text, id="m:a:s"):
    return Section(id=id, manual_id="m", doc_path="a.md", heading_path=("S",), anchor="s",
                   text=text, position=0, source_url=None)


def test_short_section_is_one_chunk():
    sec = _sec("x" * 100)
    chunks = chunk_sections([sec])
    assert len(chunks) == 1
    assert chunks[0].id == "m:a:s#0" and chunks[0].text == sec.text
    assert chunks[0].section_id == sec.id and chunks[0].manual_id == "m"


def test_long_section_split_with_overlap():
    paras = [f"para{i} " + "x" * 600 for i in range(6)]
    sec = _sec("\n\n".join(paras))
    chunks = chunk_sections([sec], max_tokens=400)
    assert len(chunks) > 1 and all(c.section_id == "m:a:s" for c in chunks)
    assert chunks[1].text.startswith(chunks[0].text.split("\n\n")[-1])
    assert [c.id for c in chunks] == [f"m:a:s#{i}" for i in range(len(chunks))]
    assert all(any(p in c.text for c in chunks) for p in paras)


def test_oversized_single_paragraph_is_kept_whole():
    chunks = chunk_sections([_sec("y" * 5000)], max_tokens=400)
    assert len(chunks) == 1 and len(chunks[0].text) == 5000
