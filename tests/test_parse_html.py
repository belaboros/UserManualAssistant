from uma.corpus.parse_html import parse_html

PAGE = """<html><body><nav>Home | Docs</nav><header>Brand</header>
<main><h1 id="pairing">Pairing</h1><p>Open the app.</p><ul><li>Tap Add</li></ul>
<h2>Confirm</h2><p>Tap OK.</p><script>x()</script></main><footer>© 2026</footer></body></html>"""


def test_html_sections_and_boilerplate_removed():
    s = parse_html(PAGE, manual_id="app", doc_path="pair.html", base_url=None)
    assert [x.heading_path for x in s] == [("Pairing",), ("Pairing", "Confirm")]
    assert "Open the app." in s[0].text and "Tap Add" in s[0].text
    joined = " ".join(x.text for x in s)
    assert "Home | Docs" not in joined and "Brand" not in joined and "©" not in joined and "x()" not in joined


def test_existing_id_used_as_anchor():
    s = parse_html(PAGE, manual_id="app", doc_path="pair.html", base_url=None)
    assert s[0].anchor == "pairing" and s[1].anchor == "confirm"


def test_html_without_headings():
    s = parse_html("<body><p>Only text.</p></body>", manual_id="m", doc_path="a.html", base_url=None)
    assert len(s) == 1 and s[0].id == "m:a:intro" and s[0].text == "Only text."


def test_falls_back_to_body_without_main():
    s = parse_html("<body><h1>A</h1><p>b</p></body>", manual_id="m", doc_path="a.html", base_url=None)
    assert s[0].text == "b"


def test_empty_slug_heading_gets_fallback_anchor():
    s = parse_html("<body><p>Intro.</p><h1>???</h1><p>Body.</p></body>",
                   manual_id="m", doc_path="a.html", base_url=None)
    assert [x.anchor for x in s] == ["", "section"]
    assert len({x.id for x in s}) == len(s)


def test_same_stem_in_different_folders_gives_distinct_ids():
    html = "<body><h1>Setup</h1><p>Body.</p></body>"
    a = parse_html(html, manual_id="m", doc_path="a/index.html", base_url=None)
    b = parse_html(html, manual_id="m", doc_path="b/index.html", base_url=None)
    assert a[0].id == "m:a/index:setup" and a[0].id != b[0].id


def test_nested_blocks_not_duplicated_and_source_url():
    s = parse_html("<body><h1>A</h1><ul><li><p>One</p></li></ul></body>",
                   manual_id="m", doc_path="a.html", base_url="https://x.io/docs/")
    assert s[0].text == "One"
    assert s[0].source_url == "https://x.io/docs/a.html#a"
