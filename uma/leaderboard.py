"""Leaderboard: per-strategy star statistics, wins and answer metrics over the question log."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from uma.log import Log

Mode = Literal["all", "blind", "labelled"]


@dataclass
class StrategyRow:
    strategy_id: str
    title: str
    avg_stars: float | None
    votes: int
    distribution: dict[int, int]
    wins: int
    avg_latency_ms: float | None
    avg_cost_usd: float | None
    not_covered_rate: float | None
    errors: int


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ratings_by_question(log: Log, mode: Mode) -> dict[str, dict[str, int]]:
    """question_id -> {strategy: stars}, in order of first vote (log insertion order)."""
    by_q: dict[str, dict[str, int]] = {}
    for v in log.votes(mode):
        by_q.setdefault(v["question_id"], {})[v["strategy"]] = v["stars"]
    return by_q


def compute_leaderboard(log: Log, titles: dict[str, str], mode: Mode = "all") -> list[StrategyRow]:
    ratings = _ratings_by_question(log, mode)
    stars: dict[str, list[int]] = defaultdict(list)
    wins: dict[str, int] = defaultdict(int)
    for per_q in ratings.values():
        for strategy, n in per_q.items():
            stars[strategy].append(n)
        if len(per_q) >= 2:
            best = max(per_q.values())
            for strategy, n in per_q.items():
                if n == best:
                    wins[strategy] += 1

    answers: dict[str, list[dict]] = defaultdict(list)
    for a in log.all_answers():
        answers[a["strategy"]].append(a)

    rows = []
    for sid, title in titles.items():
        given = stars.get(sid, [])
        ok = [a for a in answers.get(sid, []) if a["status"] != "failed"]
        rows.append(StrategyRow(
            strategy_id=sid, title=title,
            avg_stars=_mean(given), votes=len(given),
            distribution={i: given.count(i) for i in range(1, 6)},
            wins=wins.get(sid, 0),
            avg_latency_ms=_mean([a["latency_ms"] for a in ok if a["latency_ms"] is not None]),
            avg_cost_usd=_mean([a["cost_usd"] for a in ok if a["cost_usd"] is not None]),
            not_covered_rate=(
                sum(a["status"] == "not_covered" for a in ok) / len(ok) if ok else None
            ),
            errors=len(answers.get(sid, [])) - len(ok),
        ))
    rows.sort(key=lambda r: (r.avg_stars is None, -(r.avg_stars or 0), -r.votes))
    return rows


def recent_questions(log: Log, mode: str = "all", limit: int = 20) -> list[dict]:
    """Questions with at least one vote in `mode`, widest star spread first, then newest.

    Ties on `asked_at` are broken by first-vote (insertion) order, later first.
    """
    out = []
    for order, (qid, per_q) in enumerate(_ratings_by_question(log, mode).items()):  # type: ignore[arg-type]
        q = log.get_question(qid)
        if q is None:
            continue
        out.append((
            {"question_id": qid, "text": q["text"], "asked_at": q["asked_at"],
             "ratings": per_q, "spread": max(per_q.values()) - min(per_q.values())},
            order,
        ))
    out.sort(key=lambda t: (t[0]["spread"], t[0]["asked_at"], t[1]), reverse=True)
    return [q for q, _ in out[:limit]]
