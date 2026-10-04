"""Whole-context strategy: every manual goes into the prompt as a citable document."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from uma.config import Settings
from uma.corpus.models import ManualRecord, Section
from uma.corpus.store import CorpusStore
from uma.llm import LLM, LLMError
from uma.strategies.base import AnswerEvent, Citation, Failed, run_single_call
from uma.strategies.rules import ANSWERING_RULES

CORPUS_TOO_LARGE_DOC = "/docs/strategies/1-whole-context.md#avoid-when"

MECHANISM = "The complete manuals are provided as documents. Read them in full before answering."


def build_documents(manuals: list[ManualRecord], sections: list[Section]) -> list[dict]:
    """One citable custom-content document per manual; one content block per section."""
    docs: list[dict] = []
    for m in manuals:
        blocks = [
            {"type": "text", "text": f"{' › '.join(s.heading_path)}\n\n{s.text}"}
            for s in sections
            if s.manual_id == m.meta.id
        ]
        docs.append({
            "type": "document",
            "source": {"type": "content", "content": blocks},
            "title": m.meta.title,
            "citations": {"enabled": True},
        })
    if docs:
        docs[-1]["cache_control"] = {"type": "ephemeral"}
    return docs


class WholeContextStrategy:
    id = "whole_context"
    title = "Whole-context"

    def __init__(self, store: CorpusStore, llm: LLM, settings: Settings) -> None:
        self.store, self.llm, self.settings = store, llm, settings

    async def answer(self, question: str) -> AsyncIterator[AnswerEvent]:
        started = time.perf_counter()
        manuals = self.store.manuals()
        sections = self.store.sections()
        docs = build_documents(manuals, sections)
        system = f"{ANSWERING_RULES}\n{MECHANISM}"

        try:
            tokens = self.store.corpus_token_count()
            if tokens is None:
                probe = [{"role": "user", "content": [*docs, {"type": "text", "text": "?"}]}]
                tokens = await self.llm.count_tokens(system=system, messages=probe)
                self.store.set_token_count(None, tokens)
        except LLMError as e:
            yield Failed(str(e))
            return
        limit = self.settings.whole_context_max_tokens
        if tokens > limit:
            yield Failed(
                f"The manuals total {tokens:,} tokens, over the {limit:,} token limit "
                "for whole-context answering.",
                hint_doc=CORPUS_TOO_LARGE_DOC,
            )
            return

        by_doc = [[s for s in sections if s.manual_id == m.meta.id] for m in manuals]

        def resolve(c: dict) -> Citation | None:
            if c.get("type") != "content_block_location":
                return None
            di, bi = c.get("document_index"), c.get("start_block_index")
            if not isinstance(di, int) or not isinstance(bi, int):
                return None
            if not (0 <= di < len(manuals)) or not (0 <= bi < len(by_doc[di])):
                return None
            s = by_doc[di][bi]
            return Citation(manuals[di].meta.id, manuals[di].meta.title, s.id, s.heading_path,
                            c.get("cited_text", ""))

        messages = [{"role": "user", "content": [*docs, {"type": "text", "text": question}]}]
        async for event in run_single_call(
            self.llm, system, messages, resolve, started, self.settings.model, self.id
        ):
            yield event
