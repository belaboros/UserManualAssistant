"""Runs all strategies in parallel and merges their events into one SSE payload stream."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict

from uma.log import Log
from uma.strategies.base import Failed, Final, Strategy, TextDelta, TraceStep, answer_to_dict

_DONE = object()


async def _run_one(
    strategy: Strategy, question_id: str, question: str, log: Log,
    timeout_s: float, queue: asyncio.Queue,
) -> None:
    trace: list[dict] = []
    answer = None
    error: str | None = None
    try:
        try:
            async with asyncio.timeout(timeout_s) as cm:
                try:
                    async for ev in strategy.answer(question):
                        if isinstance(ev, TextDelta):
                            await queue.put({"strategy": strategy.id, "type": "delta", "text": ev.text})
                        elif isinstance(ev, TraceStep):
                            trace.append(asdict(ev))
                            await queue.put({"strategy": strategy.id, "type": "trace",
                                             "kind": ev.kind, "detail": ev.detail})
                        elif isinstance(ev, Final):
                            answer = ev.answer
                            await queue.put({"strategy": strategy.id, "type": "final",
                                             "answer": answer_to_dict(ev.answer)})
                            break
                        elif isinstance(ev, Failed):
                            error = ev.message
                            await queue.put({"strategy": strategy.id, "type": "failed",
                                             "message": ev.message, "hint_doc": ev.hint_doc})
                            break
                except Exception as e:
                    if cm.expired():
                        raise TimeoutError from e
                    raise
        except TimeoutError:
            error = f"Timed out after {timeout_s:g} s"
            await queue.put({"strategy": strategy.id, "type": "failed",
                             "message": error, "hint_doc": None})
        except Exception as e:
            error = f"Unexpected error: {type(e).__name__}"
            await queue.put({"strategy": strategy.id, "type": "failed",
                             "message": error, "hint_doc": None})
        if answer is None and error is None:
            error = "Strategy finished without an answer"
            await queue.put({"strategy": strategy.id, "type": "failed",
                             "message": error, "hint_doc": None})
        log.save_answer(question_id, strategy.id, answer=answer, error=error, trace=trace)
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
