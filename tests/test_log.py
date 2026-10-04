import pytest

from uma.llm import Usage
from uma.log import Log, VoteError
from uma.strategies.base import Answer, Citation, Metrics, answer_to_dict


def make_answer(text="Hold the button [1].", status="answered"):
    cit = Citation("m", "Manual", "m#reset", ("Setup", "Reset"), "Hold 10 s")
    metrics = Metrics(1200, Usage(100, 20, 5, 7), 0.001, ["Manual"], tool_calls=2)
    return Answer(text, [cit], status, metrics)


@pytest.fixture
def log(tmp_path):
    return Log(tmp_path / "uma.db")


@pytest.fixture
def seeded(log):
    qid = log.create_question("How do I reset?", blind=True)
    log.save_answer(qid, "rag", answer=make_answer(), error=None, trace=[{"kind": "search"}])
    log.save_answer(qid, "whole_context", answer=None, error="boom", trace=[])
    return log, qid


def test_create_and_get_question(log):
    qid = log.create_question("hi?", blind=True)
    assert len(qid) == 32
    q = log.get_question(qid)
    assert q["text"] == "hi?" and q["blind"] is True and q["asked_at"]
    assert log.get_question("nope") is None


def test_answer_roundtrip(seeded):
    log, qid = seeded
    a = log.answers_for(qid)
    rag = a["rag"]
    assert rag["status"] == "answered" and rag["error"] is None
    assert rag["text"] == "Hold the button [1]."
    assert rag["citations"][0]["heading_path"] == ["Setup", "Reset"]
    assert rag["trace"] == [{"kind": "search"}]
    assert rag["latency_ms"] == 1200 and rag["cost_usd"] == 0.001
    assert rag["input_tokens"] == 100 and rag["cache_write_tokens"] == 7
    assert rag["answer"] == answer_to_dict(make_answer())
    failed = a["whole_context"]
    assert failed["status"] == "failed" and failed["error"] == "boom"
    assert failed["answer"] is None and failed["text"] is None and failed["citations"] == []


def test_save_answer_replaces(seeded):
    log, qid = seeded
    log.save_answer(qid, "rag", answer=make_answer("new"), error=None, trace=[])
    assert log.answers_for(qid)["rag"]["text"] == "new"
    assert len(log.all_answers()) == 2


def test_vote_rejects_out_of_range(seeded):
    log, qid = seeded
    for stars in (0, 6, 3.5, "3", True):
        with pytest.raises(VoteError, match="stars"):
            log.upsert_vote(qid, "rag", stars, False)


def test_vote_rejects_unknown_question_and_answer(seeded):
    log, qid = seeded
    with pytest.raises(VoteError, match="question"):
        log.upsert_vote("nope", "rag", 3, False)
    with pytest.raises(VoteError, match="answer"):
        log.upsert_vote(qid, "agentic", 3, False)


def test_vote_on_failed_answer_rejected(seeded):
    log, qid = seeded
    with pytest.raises(VoteError, match="failed"):
        log.upsert_vote(qid, "whole_context", 3, False)


def test_vote_upsert_replaces(seeded):
    log, qid = seeded
    log.upsert_vote(qid, "rag", 2, False)
    log.upsert_vote(qid, "rag", 5, True)
    assert log.votes() == [{"question_id": qid, "strategy": "rag", "stars": 5, "blind": True}]


def test_votes_mode_filter(seeded):
    log, qid = seeded
    q2 = log.create_question("two", blind=False)
    log.save_answer(q2, "rag", answer=make_answer(), error=None, trace=[])
    log.upsert_vote(qid, "rag", 4, True)
    log.upsert_vote(q2, "rag", 3, False)
    assert [v["stars"] for v in log.votes("blind")] == [4]
    assert [v["stars"] for v in log.votes("labelled")] == [3]
    assert len(log.votes("all")) == 2


def test_reset_votes_keeps_answers(seeded):
    log, qid = seeded
    log.upsert_vote(qid, "rag", 4, False)
    log.reset_votes()
    assert log.votes() == [] and "rag" in log.answers_for(qid)


def test_export_rows(seeded):
    log, qid = seeded
    log.upsert_vote(qid, "rag", 4, True)
    (row,) = log.export_rows()
    assert row["question_text"] == "How do I reset?" and row["strategy"] == "rag"
    assert row["stars"] == 4 and row["blind"] is True and row["voted_at"]
    assert row["status"] == "answered" and row["latency_ms"] == 1200
    assert row["cost_usd"] == 0.001 and row["input_tokens"] == 100 and row["output_tokens"] == 20


def test_all_answers(seeded):
    log, qid = seeded
    rows = log.all_answers()
    assert {(r["question_id"], r["strategy"]) for r in rows} == {(qid, "rag"), (qid, "whole_context")}
    assert {r["status"] for r in rows} == {"answered", "failed"}


def test_shares_db_with_corpus_store(tmp_path):
    from uma.corpus.store import CorpusStore

    CorpusStore(tmp_path / "uma.db")
    log = Log(tmp_path / "uma.db")
    assert log.create_question("x", False)
