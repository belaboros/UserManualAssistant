import json

from uma.llm import Usage
from uma.strategies.base import (
    Answer,
    Citation,
    Metrics,
    StatusTagFilter,
    answer_to_dict,
    assemble_cited_text,
    resolve_section_markers,
    strip_status,
)
from uma.strategies.rules import AGENTIC_ADDENDUM, ANSWERING_RULES

CIT = {
    "hub": Citation("hub", "Hub", "hub-s", ("Pairing",), "Hold Link 3 s."),
    "app": Citation("app", "App", "app-s", ("Setup", "Open"), "Open the app."),
}
CIT_BY_ID = {"m:a:x": CIT["hub"]}


def run(chunks):
    f = StatusTagFilter()
    shown = "".join(f.feed(c) for c in chunks)
    rest, status, found = f.finish()
    return shown + rest, status, found


def test_tag_removed_and_detected():
    assert run(["Do X.\n<status>not_covered</status>"]) == ("Do X.\n", "not_covered", True)


def test_tag_split_across_chunks():
    assert run(["Do X. <sta", "tus>contradiction_fo", "und</status>\n"]) == (
        "Do X. ",
        "contradiction_found",
        True,
    )


def test_literal_angle_bracket_passes_through():
    text, status, found = run(["If temperature < 5 °C, ", "use <b>frost</b> mode."])
    assert text == "If temperature < 5 °C, use <b>frost</b> mode."
    assert status == "answered" and not found


def test_missing_tag_defaults_to_answered():
    assert run(["Plain answer."])[1:] == ("answered", False)


def test_invalid_status_value_defaults_to_answered():
    assert run(["x<status>maybe</status>"]) == ("x", "answered", False)


def test_char_by_char_matches_single_feed():
    text = "Answer.\n<status>not_covered</status>"
    assert run(list(text)) == run([text]) == ("Answer.\n", "not_covered", True)


def test_trailing_partial_prefix_is_released_on_finish():
    assert run(["Use <stat"]) == ("Use <stat", "answered", False)


def test_strip_status():
    assert strip_status("Hi.\n<status>answered</status>\n") == ("Hi.\n", "answered", True)


def test_assemble_cited_text_dedupes():
    blocks = [
        {"type": "text", "text": "Hold Link 3 s.", "citations": [{"k": "hub"}]},
        {"type": "text", "text": " Then open the app.", "citations": [{"k": "app"}, {"k": "hub"}]},
    ]
    text, cits = assemble_cited_text(blocks, lambda c: CIT[c["k"]])
    assert text == "Hold Link 3 s. [1] Then open the app. [2][1]"
    assert [c.section_id for c in cits] == ["hub-s", "app-s"]


def test_resolve_section_markers():
    text, cits = resolve_section_markers(
        "Do A [§m:a:x]. Do B [§bogus].", lambda sid: CIT_BY_ID.get(sid)
    )
    assert text == "Do A [1]. Do B ." and len(cits) == 1


def test_usage_add():
    u = Usage(1, 2, 3, 4) + Usage(10, 20)
    assert u == Usage(11, 22, 3, 4)


def test_answer_to_dict_is_json_safe():
    a = Answer("t [1]", [CIT["app"]], "answered", Metrics(5, Usage(1, 2), None, ["app"]))
    d = answer_to_dict(a)
    assert d["citations"][0]["heading_path"] == ["Setup", "Open"]
    assert d["metrics"]["usage"]["input_tokens"] == 1
    json.dumps(d)


def test_rules_text():
    assert "<status>not_covered</status>" in ANSWERING_RULES
    assert "[§<section_id>]" in AGENTIC_ADDENDUM


def test_chunking_never_changes_output():
    inputs = [
        "t<status>answered</status>\nmore < 5",
        "t<status>answered</status>\nTrailer < 5",
        "Do X.\n<status>not_covered</status>\n",
        "a <b> <sta c <status>contradiction_found</status>  ",
        "plain < 5 text",
    ]
    for text in inputs:
        expected = run([text])
        assert run(list(text)) == expected
        for i in range(len(text) + 1):
            for j in range(i, len(text) + 1):
                assert run([text[:i], text[i:j], text[j:]]) == expected, (text, i, j)
        assert strip_status(text) == expected
