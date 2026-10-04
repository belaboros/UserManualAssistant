from uma.strategies.web_sources import WebSources


def test_add_dedupes_by_url():
    ws = WebSources()
    assert [ws.add("a", "A"), ws.add("b", "B"), ws.add("a", "A")] == [1, 2, 1]
    assert len(ws) == 2


def test_rewrite_maps_and_drops():
    ws = WebSources()
    ws.add("https://a.example/x", "A")
    out = ws.rewrite("X [web:https://a.example/x]. Y [web:https://never.example/].")
    assert out == "X [web:1]. Y ."


def test_citation_fields():
    ws = WebSources()
    ws.add("https://a.example/x", "A page")
    c = ws.citation(1)
    assert c.kind == "web" and c.url == "https://a.example/x"
    assert c.manual_id == "a.example" and c.manual_title == "A page"
    assert c.section_id == "https://a.example/x" and c.heading_path == () and c.cited_text == ""
    assert ws.citation(9) is None
    assert ws.number("https://a.example/x") == 1 and ws.number("zz") is None
    assert ws.listing() == "[web:1] A page — https://a.example/x"
