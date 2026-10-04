"""Agentic & web strategy: a local manual phase, a web search phase, then one streamed merge (ADR 0014)."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from uma.config import WEB_SEARCH_USD_PER_SEARCH, Settings, cost_usd
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
    resolve_mixed_markers,
    strip_status,
    warn_missing_status,
)
from uma.strategies.manual_tools import MANUAL_TOOLS, ManualTools
from uma.strategies.phase import PhaseResult, run_phase
from uma.strategies.rules import AGENTIC_WEB_LOCAL, AGENTIC_WEB_MERGE_RULES, AGENTIC_WEB_SEARCH
from uma.strategies.web_sources import WebSources

logger = logging.getLogger(__name__)

_CONFLICT = "⚠ **Conflict"


def _findings(label: str, result: PhaseResult) -> str:
    gaps = "\n".join(f"- {g}" for g in result.gaps) or "None"
    return f"{label} findings:\n{result.notes or 'None'}\n\n{label} gaps:\n{gaps}"


class AgenticWebStrategy:
    id = "agentic_web"
    title = "Agentic & web"

    def __init__(self, store: CorpusStore, embedder: Embedder, llm: LLM, settings: Settings) -> None:
        self.store, self.embedder, self.llm, self.settings = store, embedder, llm, settings
        self.manual_tools = ManualTools(store, embedder)
        self.timeout_s: float = settings.agent_web_timeout_s

    async def answer(self, question: str) -> AsyncIterator[AnswerEvent]:
        started = time.perf_counter()
        sources = WebSources()

        local: PhaseResult | None = None
        async for item in run_phase(
            self.llm, phase="local", system=AGENTIC_WEB_LOCAL, prompt=question, tools=MANUAL_TOOLS,
            run_tool=self.manual_tools.run, budget=self.settings.agent_web_local_max_tool_calls,
        ):
            if isinstance(item, PhaseResult):
                local = item
            else:
                yield item
                if isinstance(item, Failed):
                    return
        assert local is not None

        web: PhaseResult | None = None
        async for item in run_phase(
            self.llm, phase="web", system=AGENTIC_WEB_SEARCH,
            prompt=f"Question:\n{question}\n\n{_findings('Manual', local)}",
            tools=[], run_tool=None, budget=self.settings.agent_web_max_searches, sources=sources,
        ):
            if isinstance(item, PhaseResult):
                web = item
            else:
                yield item
                if isinstance(item, Failed):
                    return
        assert web is not None

        content = (f"Question:\n{question}\n\n{_findings('Manual', local)}\n\n{_findings('Web', web)}\n\n"
                   f"Web sources:\n{sources.listing() or 'None'}")
        usage = local.usage + web.usage
        filt = StatusTagFilter()
        response: LLMResponse | None = None
        try:
            async for event in self.llm.stream(system=AGENTIC_WEB_MERGE_RULES,
                                               messages=[{"role": "user", "content": content}], tools=None):
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
        if response.stop_reason == "refusal":
            yield Failed("The model declined this question")
            return
        if response.stop_reason == "max_tokens":
            yield Failed(TRUNCATED)
            return

        raw = "".join(b.get("text", "") for b in response.content if b.get("type") == "text")
        text, status, found = strip_status(raw)
        if not found:
            warn_missing_status(self.id, logger)
        text, citations = resolve_mixed_markers(text, self.manual_tools.lookup, sources)
        # "⚠️" is "⚠" plus the emoji variation selector U+FE0F; both spellings mark a conflict block.
        if status == "answered" and _CONFLICT in text.replace("️", ""):
            status = "contradiction_found"
        cost = cost_usd(self.settings.model, usage.input_tokens, usage.output_tokens,
                        usage.cache_read_tokens, usage.cache_write_tokens)
        metrics = Metrics(
            latency_ms=round((time.perf_counter() - started) * 1000),
            usage=usage,
            cost_usd=None if cost is None else cost + web.web_searches * WEB_SEARCH_USD_PER_SEARCH,
            manuals_used=list(dict.fromkeys(c.manual_title for c in citations if c.kind == "manual")),
            tool_calls=local.tool_calls,
            web_searches=web.web_searches,
        )
        yield Final(Answer(text, citations, status, metrics))
