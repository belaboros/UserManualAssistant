from uma.config import load_settings
from uma.llm import FakeLLM, LLMError, text_response, tool_use_response
from uma.strategies.agentic import TOOLS, AgenticStrategy
from uma.strategies.base import Failed, Final, TraceStep
from uma.strategies.rules import AGENTIC_ADDENDUM, ANSWERING_RULES

PAIRING = "nimbus-hub:hub-guide:pairing-devices"
NOTICE = {"type": "text", "text": "Tool budget reached. Answer now with what you have."}


async def _run(store, embedder, llm, settings=None, q="pair?"):
    return [e async for e in AgenticStrategy(store, embedder, llm, settings or load_settings({})).answer(q)]


def _last_user(call):
    last = call["messages"][-1]
    assert last["role"] == "user"
    return last["content"]


def _results(call):
    return [b for b in _last_user(call) if b["type"] == "tool_result"]


async def test_tool_loop_then_cited_answer(sample_store, embedder):
    llm = FakeLLM([tool_use_response("search", {"query": "pair hub", "manual_id": None}),
                   tool_use_response("read_section", {"section_id": PAIRING}),
                   text_response(f"Hold Link 3 s [§{PAIRING}].\n<status>answered</status>")])
    events = await _run(sample_store, embedder, llm)
    traces = [e for e in events if isinstance(e, TraceStep)]
    assert [t.detail["name"] for t in traces] == ["search", "read_section"]
    assert all(t.kind == "tool_call" for t in traces)
    final = events[-1].answer
    assert final.text.strip() == "Hold Link 3 s [1]." and final.metrics.tool_calls == 2
    assert final.status == "answered"
    assert final.citations[0].section_id == PAIRING
    assert final.metrics.manuals_used == [final.citations[0].manual_title]
    assert final.metrics.usage.input_tokens == 30
    # all tool_results of a turn are in ONE user message; assistant content echoed unchanged
    assert llm.calls[1]["messages"][1]["content"] == llm.responses[0].content
    assert llm.calls[0]["system"] == f"{ANSWERING_RULES}\n\n{AGENTIC_ADDENDUM}"
    assert "<status>" not in "".join(getattr(e, "text", "") for e in events)


async def test_tool_outputs(sample_store, embedder):
    llm = FakeLLM([tool_use_response("list_manuals", {}),
                   tool_use_response("search", {"query": "pair hub", "manual_id": None}),
                   tool_use_response("read_section", {"section_id": PAIRING}),
                   text_response("done")])
    await _run(sample_store, embedder, llm)
    listing = _results(llm.calls[1])[0]["content"].splitlines()
    assert len(listing) == 3 and all(len(line.split(" | ")) == 4 for line in listing)
    assert listing[0].endswith(" sections") and listing[0].startswith("nimbus-app | ")
    lines = _results(llm.calls[2])[0]["content"].splitlines()
    assert 1 <= len(lines) <= 8
    assert all(len(line.split(" | ", 3)) == 4 and len(line.split(" | ", 3)[3]) <= 300 for line in lines)
    section = _results(llm.calls[3])[0]["content"]
    assert section.endswith(sample_store.section(PAIRING).text)


async def test_unknown_section_returns_error_result(sample_store, embedder):
    llm = FakeLLM([tool_use_response("read_section", {"section_id": "nope"}),
                   text_response("Not found.\n<status>not_covered</status>")])
    events = await _run(sample_store, embedder, llm)
    r = _results(llm.calls[1])[0]
    assert r["is_error"] is True and r["content"] == "Unknown section_id: nope"
    assert events[-1].answer.status == "not_covered" and events[-1].answer.metrics.tool_calls == 1


async def test_bad_inputs_and_unknown_tool_are_error_results(sample_store, embedder):
    llm = FakeLLM([tool_use_response("search", {"query": 5}),
                   tool_use_response("read_section", {}),
                   tool_use_response("search", {"query": "x", "manual_id": 3}),
                   tool_use_response("frobnicate", {}),
                   text_response("ok")])
    events = await _run(sample_store, embedder, llm)
    for i in range(1, 5):
        assert _results(llm.calls[i])[0]["is_error"] is True
    assert isinstance(events[-1], Final)


async def test_parallel_tool_calls_in_one_user_message(sample_store, embedder):
    first = tool_use_response("list_manuals", {})
    first.content.append({"type": "tool_use", "id": "t2", "name": "read_section",
                          "input": {"section_id": PAIRING}})
    llm = FakeLLM([first, text_response("ok")])
    await _run(sample_store, embedder, llm)
    assert len(_results(llm.calls[1])) == 2
    assert [m["role"] for m in llm.calls[1]["messages"]] == ["user", "assistant", "user"]


async def test_budget_cap(sample_store, embedder):
    llm = FakeLLM([tool_use_response("list_manuals", {}) for _ in range(4)])
    events = await _run(sample_store, embedder, llm, load_settings({"AGENT_MAX_TOOL_CALLS": "2"}))
    assert isinstance(events[-1], Failed)
    assert events[-1].message == "The agent did not finish within its tool budget"
    assert len(llm.calls) == 4  # max + 2 turns
    assert len([e for e in events if isinstance(e, TraceStep)]) == 2  # only two calls really ran
    assert "is_error" not in _results(llm.calls[1])[0] and NOTICE not in _last_user(llm.calls[1])
    assert "is_error" not in _results(llm.calls[2])[0] and _last_user(llm.calls[2]).count(NOTICE) == 1
    exhausted = _results(llm.calls[3])[0]  # reply to the 3rd call
    assert exhausted["is_error"] is True and exhausted["content"] == "Tool budget exhausted. Answer now."
    assert _last_user(llm.calls[3]).count(NOTICE) == 1


async def test_tools_are_strict_and_not_forced(sample_store, embedder):
    llm = FakeLLM([tool_use_response("list_manuals", {}), text_response("x")])
    await _run(sample_store, embedder, llm)
    assert [t["name"] for t in TOOLS] == ["list_manuals", "search", "read_section"]
    for t in TOOLS:
        assert t["strict"] is True
        schema = t["input_schema"]
        assert schema["additionalProperties"] is False
        assert sorted(schema["required"]) == sorted(schema["properties"])
    assert TOOLS[1]["input_schema"]["properties"]["manual_id"]["type"] == ["string", "null"]
    for call in llm.calls:
        assert call["tools"] == TOOLS and "tool_choice" not in call


async def test_refusal_fails(sample_store, embedder):
    r = text_response("no")
    r.stop_reason = "refusal"
    events = await _run(sample_store, embedder, FakeLLM([r]))
    assert events[-1] == Failed("The model declined this question")


async def test_llm_error_fails(sample_store, embedder):
    class Boom:
        async def stream(self, **kw):
            raise LLMError("boom")
            yield

    events = await _run(sample_store, embedder, Boom())
    assert events == [Failed("boom")]


async def test_max_tokens_stop_is_failed(sample_store, embedder):
    from uma.llm import LLMResponse, Usage
    llm = FakeLLM([tool_use_response("list_manuals", {}),
                   LLMResponse([{"type": "text", "text": "Hold the"}], "max_tokens", Usage(10, 5))])
    events = await _run(sample_store, embedder, llm)
    assert isinstance(events[-1], Failed)
    assert events[-1].message == "The answer was cut off (max_tokens reached)."
    assert not any(isinstance(e, Final) for e in events)


async def test_missing_status_tag_logs_warning(sample_store, embedder, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="uma.strategies.agentic"):
        events = await _run(sample_store, embedder, FakeLLM([text_response("No tag.")]))
    assert events[-1].answer.status == "answered"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "agentic" in warnings[0].getMessage()
