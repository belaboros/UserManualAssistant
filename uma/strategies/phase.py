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

_BUDGET_NOTICE = "Tool budget reached. Call finish_phase now with what you have."
_EXHAUSTED = "Tool budget exhausted."
_NUDGE = "Call finish_phase to end this phase."


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
    """Yield trace steps, then exactly one PhaseResult or Failed."""
    all_tools = [*tools, FINISH_PHASE_TOOL]
    messages: list[dict] = [{"role": "user", "content": prompt}]
    usage, calls, web_searches = Usage(), 0, 0
    noticed = nudged = nudged_last = False

    def close(sufficient: bool, gaps: list[str], notes: str, forced: bool):
        detail = {"phase": phase, "sufficient": sufficient, "gaps": gaps, "forced": forced}
        return (TraceStep("planner", detail),
                PhaseResult(sufficient, gaps, notes, usage, calls, web_searches, forced))

    def finished(block: dict, forced: bool):
        args = block.get("input") if isinstance(block.get("input"), dict) else {}
        return close(bool(args.get("sufficient")), list(args.get("gaps") or []), str(args.get("notes") or ""), forced)

    while True:
        response: LLMResponse | None = None
        try:
            async for event in llm.stream(system=system, messages=list(messages), tools=all_tools):
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

        if noticed:
            # One turn after the budget notice; tools it calls are not run.
            for item in close(False, ["budget exhausted"], text, True) if finish is None else finished(finish, True):
                yield item
            return
        if not uses:
            if nudged:
                for item in close(False, ["did not call finish_phase"], text, True):
                    yield item
                return
            nudged = nudged_last = True
            messages.append({"role": "user", "content": _NUDGE})
            continue

        results: list[dict] = []
        for block in uses:
            if block.get("name") == "finish_phase":
                continue
            result: dict = {"type": "tool_result", "tool_use_id": block.get("id")}
            if calls >= budget:
                result.update(content=_EXHAUSTED, is_error=True)
            else:
                calls += 1
                name, tool_input = block.get("name"), block.get("input")
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
        if calls >= budget:
            noticed = True
            results.append({"type": "text", "text": _BUDGET_NOTICE})
        nudged_last = False
        messages.append({"role": "user", "content": results})
