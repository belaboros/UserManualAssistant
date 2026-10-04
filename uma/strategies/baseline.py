"""No-retrieval baseline: only the question goes to the model (a control group, ADR 0013)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from uma.config import Settings
from uma.llm import LLM
from uma.strategies.base import AnswerEvent, Citation, run_single_call
from uma.strategies.rules import BASELINE_RULES


class BaselineStrategy:
    id = "baseline"
    title = "No retrieval"

    def __init__(self, llm: LLM, settings: Settings) -> None:
        self.llm, self.settings = llm, settings

    async def answer(self, question: str) -> AsyncIterator[AnswerEvent]:
        started = time.perf_counter()

        def resolve(_: dict) -> Citation | None:
            return None  # no documents were sent, so nothing can be cited

        messages = [{"role": "user", "content": question}]
        async for event in run_single_call(
            self.llm, BASELINE_RULES, messages, resolve, started, self.settings.model, self.id
        ):
            yield event
