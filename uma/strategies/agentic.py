"""Agentic strategy: Claude explores the manuals with tools in a manual tool-use loop (ADR 0012)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from uma.config import Settings, cost_usd
from uma.corpus.store import CorpusStore
from uma.embedding import Embedder
from uma.llm import LLM, Completed, LLMError, LLMResponse, TextChunk, Usage
from uma.strategies.base import (
    Answer,
    AnswerEvent,
    Failed,
    Final,
    Metrics,
    StatusTagFilter,
    TRUNCATED,
    TextDelta,
    TraceStep,
    resolve_section_markers,
    strip_status,
    warn_missing_status,
)
from uma.strategies.manual_tools import MANUAL_TOOLS, ManualTools, ToolError
from uma.strategies.rules import AGENTIC_ADDENDUM, ANSWERING_RULES

logger = logging.getLogger(__name__)

TOOLS = MANUAL_TOOLS

_EXHAUSTED = "Tool budget exhausted. Answer now."
_BUDGET_NOTICE = "Tool budget reached. Answer now with what you have."
_NOT_FINISHED = "The agent did not finish within its tool budget"


class AgenticStrategy:
    id = "agentic"
    title = "Agentic"

    def __init__(self, store: CorpusStore, embedder: Embedder, llm: LLM, settings: Settings) -> None:
        self.store, self.embedder, self.llm, self.settings = store, embedder, llm, settings
        self.manual_tools = ManualTools(store, embedder)

    def _run_tool(self, name: str, tool_input: object) -> str:
        return self.manual_tools.run(name, tool_input)

    # --- loop --------------------------------------------------------------------------

    async def answer(self, question: str) -> AsyncIterator[AnswerEvent]:
        started = time.perf_counter()
        cap = self.settings.agent_max_tool_calls
        system = f"{ANSWERING_RULES}\n\n{AGENTIC_ADDENDUM}"
        messages: list[dict] = [{"role": "user", "content": question}]
        usage, calls = Usage(), 0

        for _ in range(cap + 2):
            filt = StatusTagFilter()
            response: LLMResponse | None = None
            try:
                async for event in self.llm.stream(system=system, messages=list(messages), tools=TOOLS):
                    if isinstance(event, TextChunk):
                        shown = filt.feed(event.text)
                        if shown:
                            yield TextDelta(shown)
                    elif isinstance(event, Completed):
                        response = event.response
            except LLMError as e:
                yield Failed(str(e))
                return
            if response is None:
                yield Failed("The model returned no response")
                return
            rest, _, _ = filt.finish()
            if rest:
                yield TextDelta(rest)
            usage = usage + response.usage
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                yield Failed("The model declined this question")
                return
            if response.stop_reason == "max_tokens":
                yield Failed(TRUNCATED)
                return
            if response.stop_reason != "tool_use":
                raw = "".join(b.get("text", "") for b in response.content if b.get("type") == "text")
                text, status, found = strip_status(raw)
                if not found:
                    warn_missing_status(self.id, logger)
                text, citations = resolve_section_markers(text, self.manual_tools.lookup)
                metrics = Metrics(
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    usage=usage,
                    cost_usd=cost_usd(self.settings.model, usage.input_tokens, usage.output_tokens,
                                      usage.cache_read_tokens, usage.cache_write_tokens),
                    manuals_used=list(dict.fromkeys(c.manual_title for c in citations)),
                    tool_calls=calls,
                )
                yield Final(Answer(text, citations, status, metrics))
                return

            results: list[dict] = []
            for block in response.content:
                if block.get("type") != "tool_use":
                    continue
                calls += 1
                result: dict = {"type": "tool_result", "tool_use_id": block.get("id")}
                if calls > cap:
                    result.update(content=_EXHAUSTED, is_error=True)
                else:
                    name, tool_input = block.get("name"), block.get("input")
                    try:
                        # Synchronous search/store work: off the event loop (see rag.py).
                        output = await asyncio.to_thread(self._run_tool, name, tool_input)
                        result["content"] = output
                        summary = output.splitlines()[0] if output else ""
                    except ToolError as e:
                        result.update(content=str(e), is_error=True)
                        summary = "error"
                    yield TraceStep("tool_call", {"name": name, "input": tool_input, "summary": summary})
                results.append(result)
            if calls >= cap:
                results.append({"type": "text", "text": _BUDGET_NOTICE})
            messages.append({"role": "user", "content": results})

        yield Failed(_NOT_FINISHED)
