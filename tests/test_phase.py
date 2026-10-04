from uma.llm import (FakeLLM, LLMError, Usage, finish_phase_response, pause_turn_response, text_response,
                     tool_use_response, web_search_blocks)
from uma.strategies.base import Failed
from uma.strategies.manual_tools import MANUAL_TOOLS, ToolError
from uma.strategies.phase import FINISH_PHASE_TOOL, PhaseResult, run_phase, web_search_tool
from uma.strategies.web_sources import WebSources

SEARCH = {"query": "pair hub", "manual_id": None}
NOTICE = "Tool budget reached. Call finish_phase now with what you have."
NUDGE = "Call finish_phase to end this phase."


class Recorder:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, object]] = []
        self.fail = fail

    def __call__(self, name, tool_input):
        self.calls.append((name, tool_input))
        if self.fail:
            raise ToolError("bad input")
        return f"result of {name}\nmore"


async def _run(llm, run_tool=None, budget=8):
    return [e async for e in run_phase(llm, phase="local", system="sys", prompt="pair?", tools=MANUAL_TOOLS,
                                       run_tool=run_tool or Recorder(), budget=budget)]


def _last_user(call):
    last = call["messages"][-1]
    assert last["role"] == "user"
    return last["content"]


async def test_finish_phase_ends_phase():
    llm = FakeLLM([tool_use_response("search", SEARCH), finish_phase_response(True, [], "N [§s1]")])
    events = await _run(llm)
    assert [e.kind for e in events[:-1]] == ["tool_call", "planner"]
    assert events[0].detail == {"phase": "local", "name": "search", "input": SEARCH, "summary": "result of search"}
    assert events[1].detail == {"phase": "local", "sufficient": True, "gaps": [], "forced": False}
    result = events[-1]
    assert isinstance(result, PhaseResult)
    assert result.sufficient is True and result.notes == "N [§s1]" and result.gaps == []
    assert result.tool_calls == 1 and result.web_searches == 0 and result.forced is False
    assert result.usage == Usage(20, 10)
    assert llm.calls[0]["tools"][-1] == FINISH_PHASE_TOOL
    assert llm.calls[0]["tools"][:-1] == MANUAL_TOOLS
    assert llm.calls[0]["system"] == "sys"
    assert llm.calls[0]["messages"][0] == {"role": "user", "content": "pair?"}
    assert llm.calls[1]["messages"][1]["content"] == llm.responses[0].content


async def test_other_tools_run_before_finish():
    extra = tool_use_response("search", SEARCH).content
    rec = Recorder()
    llm = FakeLLM([finish_phase_response(False, ["firmware"], "n", extra=extra)])
    events = await _run(llm, rec)
    assert rec.calls == [("search", SEARCH)]
    assert [e.kind for e in events[:-1]] == ["tool_call", "planner"]
    assert events[-1].gaps == ["firmware"] and events[-1].sufficient is False and events[-1].tool_calls == 1
    assert len(llm.calls) == 1


async def test_tool_error_becomes_error_result():
    llm = FakeLLM([tool_use_response("search", SEARCH), finish_phase_response(True, [], "n")])
    events = await _run(llm, Recorder(fail=True))
    assert events[0].detail["summary"] == "error"
    result = _last_user(llm.calls[1])[0]
    assert result["is_error"] is True and result["content"] == "bad input"


async def test_budget_forces_close_with_finish():
    # The post-notice turn closes the phase, so the over-budget search shares the second turn.
    rec = Recorder()
    two = tool_use_response("search", SEARCH)
    two.content += tool_use_response("search", SEARCH).content
    llm = FakeLLM([tool_use_response("search", SEARCH), two, finish_phase_response(True, [], "done")])
    events = await _run(llm, rec, budget=2)
    assert len(rec.calls) == 2
    third = _last_user(llm.calls[2])
    assert third[1]["is_error"] is True and third[1]["content"] == "Tool budget exhausted."
    assert third[-1] == {"type": "text", "text": NOTICE}
    assert [e.kind for e in events[:-1]] == ["tool_call", "tool_call", "planner"]
    result = events[-1]
    assert result.forced is True and result.sufficient is True and result.notes == "done"
    assert result.tool_calls == 2
    assert events[-2].detail["forced"] is True


async def test_budget_forces_close_without_finish():
    rec = Recorder()
    llm = FakeLLM([tool_use_response("search", SEARCH), tool_use_response("search", SEARCH),
                   text_response("partial")])
    events = await _run(llm, rec, budget=2)
    assert _last_user(llm.calls[2])[-1] == {"type": "text", "text": NOTICE}
    result = events[-1]
    assert result.notes == "partial" and result.gaps == ["budget exhausted"]
    assert result.sufficient is False and result.forced is True and result.tool_calls == 2
    assert len(llm.calls) == 3


async def test_budget_close_ignores_tools_after_notice():
    rec = Recorder()
    llm = FakeLLM([tool_use_response("search", SEARCH), tool_use_response("search", SEARCH)])
    events = await _run(llm, rec, budget=1)
    assert len(rec.calls) == 1
    result = events[-1]
    assert result.gaps == ["budget exhausted"] and result.forced is True and result.notes == ""


async def test_plain_text_gets_one_nudge_then_closes():
    llm = FakeLLM([text_response("a"), text_response("b")])
    events = await _run(llm)
    assert _last_user(llm.calls[1]) == NUDGE
    assert [e.kind for e in events[:-1]] == ["planner"]
    result = events[-1]
    assert result.notes == "a\n\nb" and result.gaps == ["did not call finish_phase"]
    assert result.sufficient is False and result.forced is True and result.tool_calls == 0


async def test_nudge_then_finish():
    llm = FakeLLM([text_response("a"), finish_phase_response(True, [], "n")])
    events = await _run(llm)
    assert events[-1].sufficient is True and events[-1].forced is True


async def test_refusal_and_llm_error_fail():
    r = text_response("no")
    r.stop_reason = "refusal"
    events = await _run(FakeLLM([r]))
    assert events[-1] == Failed("The model declined this question")
    assert not any(isinstance(e, PhaseResult) for e in events)

    t = text_response("cut")
    t.stop_reason = "max_tokens"
    events = await _run(FakeLLM([t]))
    assert events[-1] == Failed("The answer was cut off (max_tokens reached).")

    class Boom:
        async def stream(self, **kw):
            raise LLMError("x")
            yield

    assert await _run(Boom()) == [Failed("x")]

    class Silent:
        async def stream(self, **kw):
            return
            yield

    assert await _run(Silent()) == [Failed("The model returned no response")]


# --- web phase ---------------------------------------------------------------

REMINDER = "Search the web at least once before finishing."
A = ("https://a.example/x", "A")


async def _run_web(llm, budget=8, sources=None):
    return [e async for e in run_phase(llm, phase="web", system="sys", prompt="check", tools=[],
                                       run_tool=None, budget=budget,
                                       sources=WebSources() if sources is None else sources)]


def _search_turn(query="q", results=(A,), **kw):
    from uma.llm import LLMResponse
    return LLMResponse(web_search_blocks(query, list(results) if results is not None else None, **kw),
                       "end_turn", Usage(10, 5))


def _web_tool(call):
    return next(t for t in call["tools"] if t.get("name") == "web_search")


def test_web_search_tool_shape():
    assert web_search_tool(3) == {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}


def test_web_search_blocks_shape():
    use, res = web_search_blocks("q", [A], id="srvtoolu_1")
    assert use == {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "q"}}
    assert res == {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
                   "content": [{"type": "web_search_result", "url": A[0], "title": "A"}]}
    _, err = web_search_blocks("q", None, error_code="unavailable")
    assert err["content"] == {"type": "web_search_tool_result_error", "error_code": "unavailable"}
    assert pause_turn_response([use]).stop_reason == "pause_turn"


async def test_web_search_counted_traced_and_sourced():
    sources = WebSources()
    blocks = web_search_blocks("q", [A])
    llm = FakeLLM([finish_phase_response(True, [], "Y [web:https://a.example/x] Z [web:https://b.example/]",
                                         extra=blocks)])
    events = await _run_web(llm, sources=sources)
    result = events[-1]
    assert result.web_searches == 1 and result.notes == "Y [web:1] Z " and result.tool_calls == 0
    assert result.forced is False and result.sufficient is True
    assert [e.kind for e in events[:-1]] == ["web_search", "planner"]
    assert events[0].detail == {"phase": "web", "query": "q", "result_count": 1}
    assert _web_tool(llm.calls[0]) == web_search_tool(8)
    assert llm.calls[0]["tools"][-1] == FINISH_PHASE_TOOL
    assert len(sources) == 1


async def test_duplicate_urls_one_source():
    sources = WebSources()
    llm = FakeLLM([_search_turn("q1"), finish_phase_response(True, [], "n", extra=web_search_blocks("q2", [A]))])
    events = await _run_web(llm, sources=sources)
    assert len(sources) == 1 and events[-1].web_searches == 2


async def test_finish_without_search_is_rejected():
    llm = FakeLLM([finish_phase_response(True, [], "early"),
                   finish_phase_response(True, [], "late", extra=web_search_blocks("q", [A]))])
    events = await _run_web(llm)
    rejected = _last_user(llm.calls[1])
    assert rejected == [{"type": "tool_result", "tool_use_id": llm.responses[0].content[0]["id"],
                         "content": REMINDER, "is_error": True}]
    result = events[-1]
    assert result.notes == "late" and result.forced is False and result.web_searches == 1


async def test_web_nudge_starts_with_reminder_until_searched():
    llm = FakeLLM([text_response("a"), text_response("b")])
    events = await _run_web(llm)
    assert _last_user(llm.calls[1]) == f"{REMINDER} {NUDGE}"
    assert events[-1].gaps == ["did not call finish_phase"] and events[-1].notes == "No web search was made."

    llm = FakeLLM([_search_turn(), finish_phase_response(True, [], "n")])
    await _run_web(llm)
    assert _last_user(llm.calls[1]) == NUDGE


async def test_unknown_client_tool_is_error():
    llm = FakeLLM([tool_use_response("search", SEARCH),
                   finish_phase_response(True, [], "n", extra=web_search_blocks("q", [A]))])
    events = await _run_web(llm)
    result = _last_user(llm.calls[1])[0]
    assert result["is_error"] is True and result["content"] == "Unknown tool: search"
    assert events[-1].tool_calls == 0 and events[-1].notes == "n"


async def test_pause_turn_resumed_without_user_message():
    llm = FakeLLM([pause_turn_response(web_search_blocks("q", [A])), finish_phase_response(True, [], "n")])
    events = await _run_web(llm)
    second = llm.calls[1]["messages"]
    assert second[-1]["role"] == "assistant" and second[-1]["content"] == llm.responses[0].content
    assert len(second) == 2
    assert events[-1].web_searches == 1 and events[-1].forced is False


async def test_pause_split_pairs_search_across_responses():
    use, res = web_search_blocks("q", [A])
    llm = FakeLLM([pause_turn_response([use]), pause_turn_response([res]), finish_phase_response(True, [], "n")])
    events = await _run_web(llm)
    assert events[0].kind == "web_search" and events[0].detail == {"phase": "web", "query": "q", "result_count": 1}


async def test_six_pauses_force_close():
    first = pause_turn_response([*web_search_blocks("q", [A]), {"type": "text", "text": "p0 [web:https://a.example/x]"}])
    rest = [pause_turn_response([{"type": "text", "text": f" p{i}"}]) for i in range(1, 6)]
    llm = FakeLLM([first, *rest, text_response("never")])
    events = await _run_web(llm)
    assert len(llm.calls) == 6
    assert all(c["messages"][-1]["role"] == "assistant" for c in llm.calls[1:])
    result = events[-1]
    assert result.forced is True and result.sufficient is False
    assert result.gaps == ["web search paused too often"]
    assert result.notes == "p0 [web:1] p1 p2 p3 p4 p5"
    assert events[-2].kind == "planner" and events[-2].detail["forced"] is True


async def test_all_searches_error():
    llm = FakeLLM([finish_phase_response(True, [], "n [web:https://a.example/x]",
                                         extra=web_search_blocks("q", None, error_code="unavailable"))])
    events = await _run_web(llm)
    assert events[0].detail == {"phase": "web", "query": "q", "error_code": "unavailable"}
    result = events[-1]
    assert result.notes == "Web search was unavailable." and result.sufficient is False
    assert result.web_searches == 1
    assert events[-2].detail["sufficient"] is False


async def test_one_failed_search_among_successes_keeps_notes():
    llm = FakeLLM([_search_turn("bad", None, error_code="unavailable"),
                   finish_phase_response(True, [], "n [web:https://a.example/x]", extra=web_search_blocks("q", [A]))])
    events = await _run_web(llm)
    assert events[-1].notes == "n [web:1]" and events[-1].sufficient is True


async def test_max_uses_tracks_remaining_budget():
    # The first turn pauses so the search-only turns do not trip the plain-text nudge.
    llm = FakeLLM([pause_turn_response(web_search_blocks("q1", [A])), _search_turn("q2"),
                   finish_phase_response(True, [], "done")])
    events = await _run_web(llm, budget=2)
    assert _web_tool(llm.calls[0])["max_uses"] == 2
    assert _web_tool(llm.calls[1])["max_uses"] == 1
    assert _web_tool(llm.calls[2])["max_uses"] == 1
    assert _last_user(llm.calls[2]) == NOTICE
    result = events[-1]
    assert result.forced is True and result.notes == "done" and result.web_searches == 2


async def test_budget_reached_while_paused_resumes_without_notice():
    llm = FakeLLM([pause_turn_response(web_search_blocks("q", [A])), _search_turn("q2"), text_response("t")])
    events = await _run_web(llm, budget=1)
    assert llm.calls[1]["messages"][-1]["role"] == "assistant"
    assert _last_user(llm.calls[2]) == NOTICE
    result = events[-1]
    assert result.forced is True and result.gaps == ["budget exhausted"] and result.notes == "t"


async def test_request_cap_closes_phase():
    llm = FakeLLM([tool_use_response("bogus", {}) for _ in range(20)])
    events = await _run_web(llm, budget=1)
    assert len(llm.calls) == 1 + 5 + 4
    result = events[-1]
    assert result.forced is True and result.gaps == ["budget exhausted"] and result.sufficient is False


# --- forced closes keep findings; search turns are not strikes ----------------

def _search_text_turn(text, query="q", results=(A,)):
    from uma.llm import LLMResponse
    return LLMResponse([*web_search_blocks(query, list(results)), {"type": "text", "text": text}],
                       "end_turn", Usage(10, 5))


async def test_search_text_turns_are_not_strikes():
    llm = FakeLLM([_search_text_turn("one", "q1"), _search_text_turn("two", "q2"), _search_text_turn("three", "q3"),
                   finish_phase_response(True, [], "done")])
    events = await _run_web(llm, budget=3)
    assert len(llm.calls) == 4
    assert [_last_user(c) for c in llm.calls[1:]] == [NUDGE, NUDGE, NOTICE]
    result = events[-1]
    assert result.notes == "done" and result.web_searches == 3 and result.sufficient is True


async def test_search_text_twice_keeps_both_texts():
    llm = FakeLLM([_search_text_turn("FIRST FINDINGS [web:https://a.example/x]", "q1"),
                   _search_text_turn("SECOND", "q2"), text_response("final")])
    events = await _run_web(llm, budget=2)
    assert _last_user(llm.calls[1]) == NUDGE and _last_user(llm.calls[2]) == NOTICE
    result = events[-1]
    assert result.gaps == ["budget exhausted"] and result.forced is True
    assert result.notes == "FIRST FINDINGS [web:1]\n\nSECOND\n\nfinal"


async def test_strike_close_after_search_turn_keeps_its_text():
    llm = FakeLLM([_search_text_turn("FIRST [web:https://a.example/x]"), text_response("x"), text_response("y")])
    events = await _run_web(llm)
    assert [_last_user(c) for c in llm.calls[1:]] == [NUDGE, NUDGE]
    result = events[-1]
    assert result.gaps == ["did not call finish_phase"] and result.notes == "FIRST [web:1]\n\nx\n\ny"


async def test_budget_reached_on_search_text_turn_sends_notice():
    llm = FakeLLM([_search_text_turn("only"), finish_phase_response(False, ["more"], "n")])
    events = await _run_web(llm, budget=1)
    assert _last_user(llm.calls[1]) == NOTICE
    assert events[-1].forced is True and events[-1].notes == "n"


async def test_every_rejected_finish_block_gets_a_result():
    first = finish_phase_response(True, [], "early")
    first.content += finish_phase_response(True, [], "again").content
    llm = FakeLLM([first, finish_phase_response(True, [], "late", extra=web_search_blocks("q", [A]))])
    await _run_web(llm)
    ids = [b["id"] for b in first.content]
    assert _last_user(llm.calls[1]) == [{"type": "tool_result", "tool_use_id": i, "content": REMINDER,
                                         "is_error": True} for i in ids]


async def test_web_close_without_any_search_drops_notes():
    llm = FakeLLM([text_response("unsourced a"), text_response("unsourced b")])
    events = await _run_web(llm)
    result = events[-1]
    assert result.notes == "No web search was made." and result.sufficient is False
    assert result.gaps == ["did not call finish_phase"] and result.web_searches == 0
    assert events[-2].detail["sufficient"] is False
