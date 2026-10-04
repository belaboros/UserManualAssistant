import pytest

from uma.config import WEB_SEARCH_USD_PER_SEARCH, Settings, cost_usd, load_settings
from uma.llm import (FakeLLM, LLMResponse, Usage, finish_phase_response, text_response, tool_use_response,
                     web_search_blocks)
from uma.strategies.agentic_web import AgenticWebStrategy
from uma.strategies.base import Failed, Final, TextDelta, TraceStep
from uma.strategies.manual_tools import MANUAL_TOOLS
from uma.strategies.phase import FINISH_PHASE_TOOL
from uma.strategies.rules import AGENTIC_WEB_LOCAL, AGENTIC_WEB_MERGE_RULES, AGENTIC_WEB_SEARCH

PAIRING = "nimbus-hub:hub-guide:pairing-devices"
URL = "https://a.example/x"
CONFLICT = "> ⚠ **Conflict: the manual may be out of date.**"


async def _run(store, embedder, llm, settings=None, q="pair?"):
    strategy = AgenticWebStrategy(store, embedder, llm, settings or load_settings({}))
    return [e async for e in strategy.answer(q)]


def _script(merge: str, search=None) -> FakeLLM:
    search = search or web_search_blocks("hub firmware", [(URL, "A page")])
    return FakeLLM([
        tool_use_response("read_section", {"section_id": PAIRING}),
        finish_phase_response(True, ["firmware"], f"Hold Link [§{PAIRING}]."),
        LLMResponse(search, "end_turn", Usage(10, 5)),
        finish_phase_response(True, [], f"Newer firmware [web:{URL}]."),
        text_response(merge),
    ])


async def test_three_phases_then_mixed_citations(sample_store, embedder):
    llm = _script(f"Hold Link [§{PAIRING}]. Newer firmware [web:1].\n<status>answered</status>")
    events = await _run(sample_store, embedder, llm)
    final = events[-1]
    assert isinstance(final, Final)
    a = final.answer
    assert a.text.strip() == "Hold Link [1]. Newer firmware [2]."
    assert a.status == "answered"
    assert [c.kind for c in a.citations] == ["manual", "web"]
    assert a.citations[1].url == URL
    assert a.metrics.web_searches == 1 and a.metrics.tool_calls == 1
    assert a.metrics.manuals_used == [a.citations[0].manual_title]
    assert a.metrics.usage == Usage(50, 25)
    traces = [e for e in events if isinstance(e, TraceStep)]
    assert [t.detail["phase"] for t in traces] == ["local", "local", "web", "web"]
    assert [t.kind for t in traces] == ["tool_call", "planner", "web_search", "planner"]

    local, web, merge = llm.calls[0], llm.calls[2], llm.calls[4]
    assert local["system"] == AGENTIC_WEB_LOCAL
    assert local["tools"] == [*MANUAL_TOOLS, FINISH_PHASE_TOOL]
    assert local["messages"][0] == {"role": "user", "content": "pair?"}
    assert web["system"] == AGENTIC_WEB_SEARCH
    assert [t["name"] for t in web["tools"]] == ["web_search", "finish_phase"]
    web_prompt = web["messages"][0]["content"]
    assert "pair?" in web_prompt and f"Hold Link [§{PAIRING}]." in web_prompt and "firmware" in web_prompt
    assert merge["system"] == AGENTIC_WEB_MERGE_RULES and merge["tools"] is None
    assert len(merge["messages"]) == 1 and merge["messages"][0]["role"] == "user"
    user = merge["messages"][0]["content"]
    assert "pair?" in user and f"Hold Link [§{PAIRING}]." in user
    assert "Newer firmware [web:1]." in user and f"[web:1] A page — {URL}" in user

    streamed = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert "<status>" not in streamed and "Hold Link" in streamed


async def test_cost_includes_searches(sample_store, embedder):
    settings = Settings()
    llm = _script("Done.\n<status>answered</status>")
    a = (await _run(sample_store, embedder, llm, settings))[-1].answer
    u = a.metrics.usage
    expected = cost_usd(settings.model, u.input_tokens, u.output_tokens, u.cache_read_tokens,
                        u.cache_write_tokens) + WEB_SEARCH_USD_PER_SEARCH * a.metrics.web_searches
    assert a.metrics.web_searches == 1
    assert a.metrics.cost_usd == pytest.approx(expected)


async def test_unknown_model_has_no_cost(sample_store, embedder):
    llm = _script("Done.\n<status>answered</status>")
    a = (await _run(sample_store, embedder, llm, Settings(model="nope")))[-1].answer
    assert a.metrics.cost_usd is None


async def test_conflict_block_sets_contradiction(sample_store, embedder):
    llm = _script(f"{CONFLICT} The manual says 3 s [§{PAIRING}]. The web says 5 s [web:1].\n"
                  "<status>answered</status>")
    a = (await _run(sample_store, embedder, llm))[-1].answer
    assert a.status == "contradiction_found"
    assert a.text.startswith(CONFLICT)


async def test_web_unavailable_still_answers(sample_store, embedder):
    llm = _script("Manual only [§" + PAIRING + "].\n<status>answered</status>",
                  search=web_search_blocks("hub firmware", None, error_code="unavailable"))
    events = await _run(sample_store, embedder, llm)
    assert isinstance(events[-1], Final)
    assert "Web search was unavailable." in llm.calls[4]["messages"][0]["content"]
    assert [c.kind for c in events[-1].answer.citations] == ["manual"]


async def test_phase_failure_is_failed(sample_store, embedder):
    llm = FakeLLM([LLMResponse([], "refusal", Usage(1, 1))])
    events = await _run(sample_store, embedder, llm)
    assert isinstance(events[-1], Failed) and events[-1].message == "The model declined this question"
    assert len(llm.calls) == 1


async def test_merge_refusal_is_failed(sample_store, embedder):
    llm = _script("x")
    llm.responses[-1] = LLMResponse([], "refusal", Usage(1, 1))
    events = await _run(sample_store, embedder, llm)
    assert isinstance(events[-1], Failed) and events[-1].message == "The model declined this question"


def test_merge_rules_quote_spec():
    assert CONFLICT in AGENTIC_WEB_MERGE_RULES
    assert "<status>contradiction_found</status>" in AGENTIC_WEB_MERGE_RULES
    assert "[web:<n>]" in AGENTIC_WEB_MERGE_RULES and "[§<section_id>]" in AGENTIC_WEB_MERGE_RULES
    assert "[web:<url>]" in AGENTIC_WEB_SEARCH and "[§<section_id>]" in AGENTIC_WEB_LOCAL


def test_merge_rules_cover_degraded_sources():
    assert "web search was unavailable" in AGENTIC_WEB_MERGE_RULES
    assert "the manuals could not be checked against the web" in AGENTIC_WEB_MERGE_RULES
    assert "the answer comes only from the web because the manuals do not cover it" in AGENTIC_WEB_MERGE_RULES


def test_timeout_from_settings(sample_store, embedder):
    s = AgenticWebStrategy(sample_store, embedder, FakeLLM([]), Settings(agent_web_timeout_s=42.0))
    assert s.timeout_s == 42.0 and s.id == "agentic_web" and s.title == "Agentic & web"
