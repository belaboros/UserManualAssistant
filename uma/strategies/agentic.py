"""Agentic strategy: Claude explores the manuals with tools in a manual tool-use loop (ADR 0012)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from uma.config import Settings, cost_usd
from uma.corpus.store import CorpusStore
from uma.embedding import Embedder
from uma.llm import LLM, Completed, LLMError, LLMResponse, TextChunk, Usage
from uma.search import hybrid_search
from uma.strategies.base import (
    Answer,
    AnswerEvent,
    Citation,
    Failed,
    Final,
    Metrics,
    StatusTagFilter,
    TextDelta,
    TraceStep,
    resolve_section_markers,
    strip_status,
)
from uma.strategies.rules import AGENTIC_ADDENDUM, ANSWERING_RULES

TOOLS: list[dict] = [
    {
        "name": "list_manuals",
        "description": "List every manual: id, title, owner and number of sections.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "search",
        "description": (
            "Search the manuals. Returns up to 8 lines: section_id | manual title | heading path | "
            "excerpt. Optionally restrict to one manual by id (null searches all manuals)."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "manual_id": {"type": ["string", "null"]}},
            "required": ["query", "manual_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_section",
        "description": "Read the full text of one section by its section_id.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"section_id": {"type": "string"}},
            "required": ["section_id"],
            "additionalProperties": False,
        },
    },
]

_EXHAUSTED = "Tool budget exhausted. Answer now."
_BUDGET_NOTICE = "Tool budget reached. Answer now with what you have."
_NOT_FINISHED = "The agent did not finish within its tool budget"


class _ToolError(Exception):
    """A tool failure reported back to the model as an is_error result."""


class AgenticStrategy:
    id = "agentic"
    title = "Agentic"

    def __init__(self, store: CorpusStore, embedder: Embedder, llm: LLM, settings: Settings) -> None:
        self.store, self.embedder, self.llm, self.settings = store, embedder, llm, settings
        self._titles = {m.meta.id: m.meta.title for m in store.manuals()}

    # --- tools -------------------------------------------------------------------------

    def _run_tool(self, name: str, tool_input: object) -> str:
        args = tool_input if isinstance(tool_input, dict) else {}
        if name == "list_manuals":
            return "\n".join(
                f"{m.meta.id} | {m.meta.title} | {m.meta.owner} | {m.section_count} sections"
                for m in self.store.manuals()
            )
        if name == "search":
            query, manual_id = args.get("query"), args.get("manual_id")
            if not isinstance(query, str) or not (manual_id is None or isinstance(manual_id, str)):
                raise _ToolError("search needs query (string) and manual_id (string or null)")
            hits = hybrid_search(self.store, self.embedder, query, k=8, manual_id=manual_id)
            if not hits:
                return "No results."
            return "\n".join(
                f"{h.section.id} | {self._titles.get(h.chunk.manual_id, h.chunk.manual_id)} | "
                f"{' › '.join(h.section.heading_path)} | {' '.join(h.chunk.text[:300].split())}"
                for h in hits
            )
        if name == "read_section":
            section_id = args.get("section_id")
            if not isinstance(section_id, str):
                raise _ToolError("read_section needs section_id (string)")
            section = self.store.section(section_id)
            if section is None:
                raise _ToolError(f"Unknown section_id: {section_id}")
            return f"{' › '.join(section.heading_path)}\n\n{section.text}"
        raise _ToolError(f"Unknown tool: {name}")

    def _lookup(self, section_id: str) -> Citation | None:
        section = self.store.section(section_id)
        if section is None:
            return None
        title = self._titles.get(section.manual_id, section.manual_id)
        return Citation(section.manual_id, title, section.id, section.heading_path, "")

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
            if response.stop_reason != "tool_use":
                raw = "".join(b.get("text", "") for b in response.content if b.get("type") == "text")
                text, status, _ = strip_status(raw)
                text, citations = resolve_section_markers(text, self._lookup)
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
                        output = self._run_tool(name, tool_input)
                        result["content"] = output
                        summary = output.splitlines()[0] if output else ""
                    except _ToolError as e:
                        result.update(content=str(e), is_error=True)
                        summary = "error"
                    yield TraceStep("tool_call", {"name": name, "input": tool_input, "summary": summary})
                results.append(result)
            if calls >= cap:
                results.append({"type": "text", "text": _BUDGET_NOTICE})
            messages.append({"role": "user", "content": results})

        yield Failed(_NOT_FINISHED)
