import dataclasses

import pytest

from uma.leaderboard import compute_leaderboard, recent_questions
from uma.llm import Usage
from uma.log import Log
from uma.strategies.base import Answer, Metrics

TITLES = {"whole_context": "Whole context", "rag": "RAG", "agentic": "Agentic"}


def ans(latency, cost, status="answered"):
    return Answer("text", [], status, Metrics(latency, Usage(1, 1, 0, 0), cost, ["M"], tool_calls=0))


def put(log, qid, strategy, latency=1000, cost=0.001, status="answered"):
    log.save_answer(qid, strategy, answer=ans(latency, cost, status), error=None, trace=[])


@pytest.fixture
def seeded_log(tmp_path):
    log = Log(tmp_path / "uma.db")
    q1 = log.create_question("q1", blind=False)
    q2 = log.create_question("q2", blind=True)
    q3 = log.create_question("q3", blind=False)
    q4 = log.create_question("q4", blind=False)
    # q1: wc 5, rag 3, agentic 5 (labelled)
    put(log, q1, "whole_context", 1000, 0.001)
    put(log, q1, "rag", 1000, 0.001)
    put(log, q1, "agentic", 4000, 0.004)
    for s, n in (("whole_context", 5), ("rag", 3), ("agentic", 5)):
        log.upsert_vote(q1, s, n, False)
    # q2: wc 4 (labelled), agentic 4 (blind); rag answered but not rated
    put(log, q2, "whole_context", 2000, 0.002)
    put(log, q2, "rag", 1000, 0.001)
    put(log, q2, "agentic", 2000, 0.002)
    log.upsert_vote(q2, "whole_context", 4, False)
    log.upsert_vote(q2, "agentic", 4, True)
    # q3: only rag rated
    put(log, q3, "rag", 3000, 0.003)
    log.upsert_vote(q3, "rag", 3, False)
    # q4: rag not_covered, whole_context failed, no votes
    put(log, q4, "rag", 2000, 0.002, status="not_covered")
    log.save_answer(q4, "whole_context", answer=None, error="boom", trace=[])
    return log


def test_averages_distribution_and_ranking(seeded_log):
    rows = compute_leaderboard(seeded_log, TITLES)
    assert [r.strategy_id for r in rows][0] in {"whole_context", "agentic"}
    assert rows[-1].strategy_id == "rag"
    assert rows[-1].distribution == {1: 0, 2: 0, 3: 2, 4: 0, 5: 0}
    assert rows[0].avg_stars == 4.5 and rows[0].votes == 2
    assert rows[0].title in TITLES.values()
    assert dataclasses.asdict(rows[0])["distribution"][5] == 1


def test_wins_with_ties(seeded_log):
    rows = {r.strategy_id: r for r in compute_leaderboard(seeded_log, TITLES)}
    assert (rows["whole_context"].wins, rows["agentic"].wins, rows["rag"].wins) == (2, 2, 0)


def test_blind_filter(seeded_log):
    rows = {r.strategy_id: r for r in compute_leaderboard(seeded_log, TITLES, mode="blind")}
    assert rows["agentic"].votes == 1 and rows["rag"].avg_stars is None
    assert rows["whole_context"].votes == 0 and rows["agentic"].wins == 0  # one rated strategy: no win


def test_errors_and_not_covered_rate(seeded_log):
    rows = {r.strategy_id: r for r in compute_leaderboard(seeded_log, TITLES)}
    rag = rows["rag"]  # answers: 1000/0.001, 1000/0.001, 3000/0.003, 2000/0.002 (not_covered)
    assert rag.avg_latency_ms == 1750 and rag.avg_cost_usd == pytest.approx(0.00175)
    assert rag.not_covered_rate == 0.25 and rag.errors == 0
    wc = rows["whole_context"]  # two answered (1000, 2000), one failed
    assert wc.errors == 1 and wc.avg_latency_ms == 1500 and wc.not_covered_rate == 0.0
    # metrics ignore the vote mode
    blind = {r.strategy_id: r for r in compute_leaderboard(seeded_log, TITLES, mode="blind")}
    assert blind["rag"].avg_latency_ms == 1750 and blind["whole_context"].errors == 1


def test_empty_log_lists_all_strategies(tmp_path):
    log = Log(tmp_path / "e.db")
    rows = compute_leaderboard(log, TITLES)
    assert {r.strategy_id for r in rows} == set(TITLES)
    for r in rows:
        assert r.avg_stars is None and r.votes == 0 and r.wins == 0 and r.errors == 0
        assert r.avg_latency_ms is None and r.avg_cost_usd is None and r.not_covered_rate is None
        assert r.distribution == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    assert recent_questions(log) == []


def test_recent_questions_sorted_by_spread(seeded_log):
    recent = recent_questions(seeded_log)
    assert [q["text"] for q in recent] == ["q1", "q3", "q2"]  # spread 2, then 0s newest first
    assert recent[0]["ratings"] == {"whole_context": 5, "rag": 3, "agentic": 5}
    assert recent[0]["spread"] == 2 and recent[0]["asked_at"] and recent[0]["question_id"]
    assert [q["text"] for q in recent_questions(seeded_log, mode="blind")] == ["q2"]
    assert recent_questions(seeded_log, mode="blind")[0]["ratings"] == {"agentic": 4}
    assert len(recent_questions(seeded_log, limit=1)) == 1
