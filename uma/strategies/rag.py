"""RAG strategy: hybrid-search the top chunks, send them as citable documents."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from uma.config import Settings
from uma.corpus.store import CorpusStore
from uma.embedding import Embedder
from uma.llm import LLM
from uma.search import SearchHit, retrieve_for_rag
from uma.strategies.base import AnswerEvent, Citation, TraceStep, run_single_call
from uma.strategies.rules import ANSWERING_RULES

MECHANISM = "Excerpts retrieved for this question are provided as documents."


class RagStrategy:
    id = "rag"
    title = "RAG"

    def __init__(self, store: CorpusStore, embedder: Embedder, llm: LLM, settings: Settings) -> None:
        self.store, self.embedder, self.llm, self.settings = store, embedder, llm, settings

    async def answer(self, question: str) -> AsyncIterator[AnswerEvent]:
        started = time.perf_counter()
        hits = retrieve_for_rag(self.store, self.embedder, question, self.settings.rag_top_k)
        titles = {m.meta.id: m.meta.title for m in self.store.manuals()}

        def title_of(h: SearchHit) -> str:
            return titles.get(h.chunk.manual_id, h.chunk.manual_id)

        yield TraceStep("retrieved", {"chunks": [
            {
                "section_id": h.section.id,
                "manual_title": title_of(h),
                "heading_path": list(h.section.heading_path),
                "score": float(h.score),
            }
            for h in hits
        ]})

        docs = [
            {
                "type": "document",
                "source": {"type": "content", "content": [{"type": "text", "text": h.chunk.text}]},
                "title": f"{title_of(h)} — {' › '.join(h.section.heading_path)}",
                "citations": {"enabled": True},
            }
            for h in hits
        ]

        def resolve(c: dict) -> Citation | None:
            if c.get("type") != "content_block_location":
                return None
            di = c.get("document_index")
            if not isinstance(di, int) or not (0 <= di < len(hits)):
                return None
            h = hits[di]
            return Citation(h.chunk.manual_id, title_of(h), h.section.id, h.section.heading_path,
                            c.get("cited_text", ""))

        system = f"{ANSWERING_RULES}\n{MECHANISM}"
        messages = [{"role": "user", "content": [*docs, {"type": "text", "text": question}]}]
        async for event in run_single_call(
            self.llm, system, messages, resolve, started, self.settings.model, self.id
        ):
            yield event
