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


def test_web_citation_serialises():
    web = Citation("example.com", "Page", "https://example.com/a", (), "", kind="web", url="https://example.com/a")
    answer = Answer("x [1]", [web], "answered", Metrics(1, Usage(1, 1, 0, 0), None, []))
    d = answer_to_dict(answer)
    assert d["citations"][0]["kind"] == "web" and d["citations"][0]["url"] == "https://example.com/a"
    json.dumps(d)
    assert CIT["hub"].kind == "manual" and CIT["hub"].url is None


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


# --- run_single_call -------------------------------------------------------------------

import logging  # noqa: E402
import time  # noqa: E402

from uma.llm import FakeLLM, LLMResponse, text_response  # noqa: E402
from uma.strategies.base import Failed, Final, run_single_call  # noqa: E402


async def _single(llm, **kw):
    return [e async for e in run_single_call(
        llm, "sys", [{"role": "user", "content": "q"}], lambda c: None, time.perf_counter(),
        "claude-sonnet-5-5", **kw)]


async def test_run_single_call_max_tokens_is_failed():
    llm = FakeLLM([LLMResponse([{"type": "text", "text": "Hold the"}], "max_tokens", Usage(10, 5))])
    events = await _single(llm)
    assert isinstance(events[-1], Failed)
    assert events[-1].message == "The answer was cut off (max_tokens reached)."
    assert not any(isinstance(e, Final) for e in events)


async def test_run_single_call_missing_tag_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="uma.strategies.base"):
        events = await _single(FakeLLM([text_response("No tag here.")]), strategy_id="rag")
    assert events[-1].answer.status == "answered"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "rag" in warnings[0].getMessage()


async def test_run_single_call_valid_tag_logs_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger="uma.strategies.base"):
        await _single(FakeLLM([text_response("Ok.\n<status>not_covered</status>")]))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_resolve_mixed_markers_shares_numbering():
    from uma.strategies.base import resolve_mixed_markers
    from uma.strategies.web_sources import WebSources

    s1 = Citation("m", "M", "s1", ("H",), "t")
    ws = WebSources()
    ws.add("https://a.example/x", "A")
    text, cits = resolve_mixed_markers(
        "A [§s1]. B [web:1]. C [§s1]. D [web:9]. E [§zz].",
        lambda sid: s1 if sid == "s1" else None, ws)
    assert text == "A [1]. B [2]. C [1]. D . E ."
    assert cits == [s1, ws.citation(1)]
