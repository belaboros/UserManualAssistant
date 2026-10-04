from uma.llm import FakeLLM, LLMError, Usage, finish_phase_response, text_response, tool_use_response
from uma.strategies.base import Failed
from uma.strategies.manual_tools import MANUAL_TOOLS, ToolError
from uma.strategies.phase import FINISH_PHASE_TOOL, PhaseResult, run_phase

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
    assert result.notes == "b" and result.gaps == ["did not call finish_phase"]
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
