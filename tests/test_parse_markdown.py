from uma.corpus.parse_markdown import parse_markdown

MD = "# Setup\nIntro text.\n## Wi-Fi\nConnect it.\n## Reset\nHold 10 s.\n# Troubleshooting\n## Reset\nAgain.\n"


def test_heading_paths_and_text():
    s = parse_markdown(MD, manual_id="t2", doc_path="guide.md", base_url=None)
    assert [x.heading_path for x in s] == [("Setup",), ("Setup", "Wi-Fi"), ("Setup", "Reset"),
                                          ("Troubleshooting", "Reset")]
    assert s[1].text == "Connect it." and s[1].position == 1


def test_duplicate_headings_get_unique_anchors():
    s = parse_markdown(MD, manual_id="t2", doc_path="guide.md", base_url=None)
    assert [x.anchor for x in s] == ["setup", "wi-fi", "reset", "reset-1"]
    assert len({x.id for x in s}) == len(s)
    assert s[3].id == "t2:guide:reset-1"


def test_text_without_headings_becomes_intro_section():
    s = parse_markdown("Just a paragraph.\n\n# Later\nMore.", manual_id="m", doc_path="a.md", base_url=None)
    assert s[0].anchor == "" and s[0].id == "m:a:intro" and s[0].text == "Just a paragraph."


def test_heading_without_body_is_skipped_but_kept_in_path():
    s = parse_markdown("# A\n## B\nBody.", manual_id="m", doc_path="a.md", base_url=None)
    assert [x.heading_path for x in s] == [("A", "B")]


def test_source_url():
    s = parse_markdown("# Wi-Fi\nx", manual_id="m", doc_path="docs/net.md", base_url="https://ex.com/m/")
    assert s[0].source_url == "https://ex.com/m/docs/net.md#wi-fi"


def test_lists_and_code_kept_as_text():
    s = parse_markdown("# A\n- one\n- two\n\n```\ncode\n```", manual_id="m", doc_path="a.md", base_url=None)
    assert "one" in s[0].text and "code" in s[0].text
