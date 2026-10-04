import asyncio

from uma.llm import Usage
from uma.log import Log
from uma.runner import run_question
from uma.strategies.base import Answer, Failed, Final, Metrics, TextDelta, TraceStep


class ScriptedStrategy:
    def __init__(self, id, *, delay=0.0, text="x", raises=None, fail=None):
        self.id, self.title = id, id.upper()
        self.delay, self.text, self.raises, self.fail = delay, text, raises, fail
        self.closed = False

    async def answer(self, question):
        try:
            yield TraceStep("search", {"q": question})
            await asyncio.sleep(self.delay)
            if self.raises:
                raise self.raises
            if self.fail:
                yield Failed(self.fail, hint_doc="docs/x.md")
                return
            yield TextDelta(self.text)
            yield Final(Answer(self.text, [], "answered", Metrics(5, Usage(1, 2), None, [])))
        finally:
            self.closed = True


def setup(tmp_path):
    log = Log(tmp_path / "uma.db")
    return log, log.create_question("q", False)


async def test_runner_runs_in_parallel_and_persists(tmp_path):
    log, qid = setup(tmp_path)
    slow, fast = ScriptedStrategy("a", delay=0.2, text="A"), ScriptedStrategy("b", text="B")
    events = [e async for e in run_question(qid, "q", [slow, fast], log, timeout_s=5)]
    assert [e["strategy"] for e in events if e["type"] == "final"] == ["b", "a"]
    assert events[-1] == {"type": "done"}
    for s in "ab":
        kinds = [e["type"] for e in events if e.get("strategy") == s]
        assert kinds == ["trace", "delta", "final"]
    assert events[0]["type"] == "trace" and events[0]["detail"] == {"q": "q"}
    saved = log.answers_for(qid)
    assert set(saved) == {"a", "b"} and saved["a"]["trace"] == [{"kind": "search", "detail": {"q": "q"}}]


async def test_runner_isolates_exceptions(tmp_path):
    log, qid = setup(tmp_path)
    bad = ScriptedStrategy("bad", raises=KeyError("k"))
    good = ScriptedStrategy("good")
    events = [e async for e in run_question(qid, "q", [bad, good], log, timeout_s=5)]
    failed = [e for e in events if e["type"] == "failed"]
    assert failed == [{"strategy": "bad", "type": "failed",
                       "message": "Unexpected error: KeyError", "hint_doc": None}]
    assert [e["strategy"] for e in events if e["type"] == "final"] == ["good"]
    assert log.answers_for(qid)["bad"]["error"] == "Unexpected error: KeyError"
    assert log.answers_for(qid)["good"]["status"] == "answered"


async def test_runner_timeout(tmp_path):
    log, qid = setup(tmp_path)
    s = ScriptedStrategy("slow", delay=1)
    events = [e async for e in run_question(qid, "q", [s], log, timeout_s=0.05)]
    assert events[-2]["message"] == "Timed out after 0.05 s"
    assert log.answers_for(qid)["slow"]["error"] == "Timed out after 0.05 s"


async def test_runner_persists_reported_failure(tmp_path):
    log, qid = setup(tmp_path)
    s = ScriptedStrategy("f", fail="nope")
    events = [e async for e in run_question(qid, "q", [s], log, timeout_s=5)]
    assert {"strategy": "f", "type": "failed", "message": "nope", "hint_doc": "docs/x.md"} in events
    assert log.answers_for(qid)["f"]["error"] == "nope"


async def test_runner_cleans_up_when_consumer_stops(tmp_path):
    log, qid = setup(tmp_path)
    s = ScriptedStrategy("slow", delay=10)
    gen = run_question(qid, "q", [s], log, timeout_s=30)
    first = await gen.__anext__()
    assert first["type"] == "trace"
    await gen.aclose()
    await asyncio.sleep(0)
    assert s.closed
