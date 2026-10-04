"""One phase of the Agentic & web strategy: a bounded tool loop ended by the finish_phase planner tool."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal

from uma.llm import LLM, Completed, LLMError, LLMResponse, Usage
from uma.strategies.base import Failed, TRUNCATED, TraceStep
from uma.strategies.manual_tools import ToolError
from uma.strategies.web_sources import WebSources

FINISH_PHASE_TOOL: dict = {
    "name": "finish_phase",
    "description": "Call when this phase has gathered enough, or cannot gather more. Ends the phase.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "sufficient": {"type": "boolean"},
            "gaps": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"},
        },
        "required": ["sufficient", "gaps", "notes"],
        "additionalProperties": False,
    },
}


def web_search_tool(max_uses: int) -> dict:
    """The server-side web search tool; Anthropic runs the searches, the client only echoes the blocks."""
    return {"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}


_BUDGET_NOTICE = "Tool budget reached. Call finish_phase now with what you have."
_EXHAUSTED = "Tool budget exhausted."
_NUDGE = "Call finish_phase to end this phase."
_SEARCH_REMINDER = "Search the web at least once before finishing."
_UNAVAILABLE = "Web search was unavailable."
_MAX_RESUMPTIONS = 5
_EXTRA_REQUESTS = 4  # nudge, budget notice and slack, on top of budget + resumptions


@dataclass
class PhaseResult:
    sufficient: bool
    gaps: list[str]
    notes: str
    usage: Usage
    tool_calls: int
    web_searches: int
    forced: bool


async def run_phase(
    llm: LLM,
    *,
    phase: Literal["local", "web"],
    system: str,
    prompt: str,
    tools: list[dict],
    run_tool: Callable[[str, object], str] | None,
    budget: int,
    sources: WebSources | None = None,
) -> AsyncIterator[TraceStep | PhaseResult | Failed]:
    """Yield trace steps, then exactly one PhaseResult or Failed.

    In the web phase the budget counts server-side searches, `pause_turn` is resumed without a new
    user message, finish_phase is refused until one search has run, and notes get numbered web markers.
    """
    web = phase == "web"
    if web and sources is None:
        sources = WebSources()
    messages: list[dict] = [{"role": "user", "content": prompt}]
    usage, calls, web_searches = Usage(), 0, 0
    requests = pauses = 0
    max_requests = budget + _MAX_RESUMPTIONS + _EXTRA_REQUESTS
    queries: dict[str, object] = {}  # server_tool_use id -> query, until its result arrives
    searched_ok = resuming = False
    turn_text = ""  # assistant text of the current turn, across pause_turn resumptions
    noticed = nudged = nudged_last = False

    def request_tools() -> list[dict]:
        if not web:
            return [*tools, FINISH_PHASE_TOOL]
        return [*tools, web_search_tool(max(budget - web_searches, 1)), FINISH_PHASE_TOOL]

    def budget_reached() -> bool:
        return (web_searches if web else calls) >= budget

    def close(sufficient: bool, gaps: list[str], notes: str, forced: bool):
        if web:
            if web_searches and not searched_ok:
                sufficient, notes = False, _UNAVAILABLE
            else:
                notes = sources.rewrite(notes)
        detail = {"phase": phase, "sufficient": sufficient, "gaps": gaps, "forced": forced}
        return (TraceStep("planner", detail),
                PhaseResult(sufficient, gaps, notes, usage, calls, web_searches, forced))

    def finished(block: dict, forced: bool):
        args = block.get("input") if isinstance(block.get("input"), dict) else {}
        return close(bool(args.get("sufficient")), list(args.get("gaps") or []), str(args.get("notes") or ""), forced)

    while True:
        if requests >= max_requests:
            # Defensive cap: closes like the budget case, without another request.
            for item in close(False, ["budget exhausted"], turn_text, True):
                yield item
            return
        requests += 1
        response: LLMResponse | None = None
        try:
            async for event in llm.stream(system=system, messages=list(messages), tools=request_tools()):
                if isinstance(event, Completed):
                    response = event.response
        except LLMError as e:
            yield Failed(str(e))
            return
        if response is None:
            yield Failed("The model returned no response")
            return
        usage = usage + response.usage
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "refusal":
            yield Failed("The model declined this question")
            return
        if response.stop_reason == "max_tokens":
            yield Failed(TRUNCATED)
            return

        uses = [b for b in response.content if b.get("type") == "tool_use"]
        finish = next((b for b in uses if b.get("name") == "finish_phase"), None)
        text = "".join(b.get("text", "") for b in response.content if b.get("type") == "text")
        turn_text = turn_text + text if resuming else text

        if web:
            for block in response.content:
                kind = block.get("type")
                if kind == "server_tool_use" and block.get("name") == "web_search":
                    web_searches += 1
                    queries[block.get("id")] = (block.get("input") or {}).get("query")
                elif kind == "web_search_tool_result":
                    query, content = queries.pop(block.get("tool_use_id"), None), block.get("content")
                    if isinstance(content, list):
                        searched_ok = True
                        for r in content:
                            if r.get("type") == "web_search_result" and r.get("url"):
                                sources.add(r["url"], r.get("title") or r["url"])
                        yield TraceStep("web_search", {"phase": phase, "query": query, "result_count": len(content)})
                    else:
                        error_code = content.get("error_code") if isinstance(content, dict) else None
                        yield TraceStep("web_search", {"phase": phase, "query": query, "error_code": error_code})

        if response.stop_reason == "pause_turn":
            # The API resumes a paused turn when the conversation is sent back unchanged.
            pauses += 1
            if pauses > _MAX_RESUMPTIONS:
                for item in close(False, ["web search paused too often"], turn_text, True):
                    yield item
                return
            resuming = True
            continue
        resuming = False

        if noticed:
            # One turn after the budget notice; tools it calls are not run.
            for item in close(False, ["budget exhausted"], turn_text, True) if finish is None else finished(finish, True):
                yield item
            return
        if not uses:
            if nudged:
                for item in close(False, ["did not call finish_phase"], turn_text, True):
                    yield item
                return
            if web and budget_reached():
                # Searches in this turn used up the budget.
                noticed = True
                messages.append({"role": "user", "content": _BUDGET_NOTICE})
                continue
            nudged = nudged_last = True
            nudge = f"{_SEARCH_REMINDER} {_NUDGE}" if web and web_searches == 0 else _NUDGE
            messages.append({"role": "user", "content": nudge})
            continue

        results: list[dict] = []
        for block in uses:
            name = block.get("name")
            result: dict = {"type": "tool_result", "tool_use_id": block.get("id")}
            if name == "finish_phase":
                if web and web_searches == 0 and block is finish:
                    result.update(content=_SEARCH_REMINDER, is_error=True)
                    results.append(result)
                    finish = None
                continue
            if run_tool is None:
                result.update(content=f"Unknown tool: {name}", is_error=True)
            elif calls >= budget:
                result.update(content=_EXHAUSTED, is_error=True)
            else:
                calls += 1
                tool_input = block.get("input")
                try:
                    output = await asyncio.to_thread(run_tool, name, tool_input)
                    result["content"] = output
                    summary = output.splitlines()[0] if output else ""
                except ToolError as e:
                    result.update(content=str(e), is_error=True)
                    summary = "error"
                yield TraceStep("tool_call", {"phase": phase, "name": name, "input": tool_input, "summary": summary})
            results.append(result)

        if finish is not None:
            for item in finished(finish, nudged_last):
                yield item
            return
        if budget_reached():
            noticed = True
            results.append({"type": "text", "text": _BUDGET_NOTICE})
        nudged_last = False
        messages.append({"role": "user", "content": results})
