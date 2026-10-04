"""Runs all strategies in parallel and merges their events into one SSE payload stream."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import asdict

from uma.log import Log
from uma.strategies.base import Failed, Final, Strategy, TextDelta, TraceStep, answer_to_dict

logger = logging.getLogger(__name__)
_DONE = object()


async def _run_one(
    strategy: Strategy, question_id: str, question: str, log: Log,
    timeout_s: float, queue: asyncio.Queue,
) -> None:
    trace: list[dict] = []
    answer = None
    error: str | None = None

    async def emit(payload: dict) -> None:
        await queue.put({"strategy": strategy.id, **payload})

    cm = asyncio.timeout(timeout_s)
    try:
        try:
            async with cm, aclosing(strategy.answer(question)) as events:
                async for ev in events:
                    if isinstance(ev, TextDelta):
                        await emit({"type": "delta", "text": ev.text})
                    elif isinstance(ev, TraceStep):
                        trace.append(asdict(ev))
                        await emit({"type": "trace", "kind": ev.kind, "detail": ev.detail})
                    elif isinstance(ev, Final):
                        answer = ev.answer
                        await emit({"type": "final", "answer": answer_to_dict(ev.answer)})
                        break
                    elif isinstance(ev, Failed):
                        error = ev.message
                        await emit({"type": "failed", "message": ev.message, "hint_doc": ev.hint_doc})
                        break
        except Exception as e:
            if isinstance(e, TimeoutError) and cm.expired():
                error = f"Timed out after {timeout_s:g} s"
            else:
                error = f"Unexpected error: {type(e).__name__}"
            await emit({"type": "failed", "message": error, "hint_doc": None})
        if answer is None and error is None:
            error = "Strategy finished without an answer"
            await emit({"type": "failed", "message": error, "hint_doc": None})
        try:
            log.save_answer(question_id, strategy.id, answer=answer, error=error, trace=trace)
        except Exception:
            logger.exception("Failed to save answer for strategy %s", strategy.id)
    finally:
        await queue.put(_DONE)


async def run_question(
    question_id: str, question: str, strategies: list[Strategy], log: Log, timeout_s: float
) -> AsyncIterator[dict]:
    queue: asyncio.Queue = asyncio.Queue()
    tasks = [
        asyncio.create_task(_run_one(s, question_id, question, log, timeout_s, queue))
        for s in strategies
    ]
    try:
        remaining = len(tasks)
        while remaining:
            item = await queue.get()
            if item is _DONE:
                remaining -= 1
            else:
                yield item
        yield {"type": "done"}
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
