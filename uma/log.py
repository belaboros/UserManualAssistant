"""Question log: questions, answers and votes in SQLite (same file as the corpus store)."""

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from uma.strategies.base import Answer, answer_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY, text TEXT NOT NULL, blind INTEGER NOT NULL, asked_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS answers(
  question_id TEXT NOT NULL, strategy TEXT NOT NULL, status TEXT NOT NULL,
  text TEXT, citations_json TEXT, trace_json TEXT NOT NULL, error TEXT,
  latency_ms INTEGER, input_tokens INTEGER, output_tokens INTEGER,
  cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_usd REAL,
  manuals_used_json TEXT, tool_calls INTEGER,
  PRIMARY KEY(question_id, strategy));
CREATE TABLE IF NOT EXISTS votes(
  question_id TEXT NOT NULL, strategy TEXT NOT NULL, stars INTEGER NOT NULL,
  blind INTEGER NOT NULL, voted_at TEXT NOT NULL,
  UNIQUE(question_id, strategy));
"""


class VoteError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _answer_row(r: sqlite3.Row) -> dict:
    failed = r["error"] is not None
    d = {
        "question_id": r["question_id"], "strategy": r["strategy"],
        "status": "failed" if failed else r["status"],
        "text": r["text"],
        "citations": json.loads(r["citations_json"]) if r["citations_json"] else [],
        "trace": json.loads(r["trace_json"]),
        "error": r["error"],
        "latency_ms": r["latency_ms"], "input_tokens": r["input_tokens"],
        "output_tokens": r["output_tokens"], "cache_read_tokens": r["cache_read_tokens"],
        "cache_write_tokens": r["cache_write_tokens"], "cost_usd": r["cost_usd"],
        "manuals_used": json.loads(r["manuals_used_json"]) if r["manuals_used_json"] else [],
        "tool_calls": r["tool_calls"],
        "answer": None,
    }
    if not failed:
        d["answer"] = {
            "text": r["text"], "citations": d["citations"], "status": r["status"],
            "metrics": {
                "latency_ms": r["latency_ms"],
                "usage": {
                    "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
                    "cache_read_tokens": r["cache_read_tokens"],
                    "cache_write_tokens": r["cache_write_tokens"],
                },
                "cost_usd": r["cost_usd"], "manuals_used": d["manuals_used"],
                "tool_calls": r["tool_calls"],
            },
        }
    return d


class Log:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c, c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _run(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with closing(self._conn()) as c, c:
            return c.execute(sql, params).fetchall()

    def create_question(self, text: str, blind: bool) -> str:
        qid = uuid.uuid4().hex
        self._run("INSERT INTO questions VALUES(?,?,?,?)", (qid, text, int(blind), _now()))
        return qid

    def get_question(self, question_id: str) -> dict | None:
        rows = self._run("SELECT * FROM questions WHERE id=?", (question_id,))
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "text": r["text"], "blind": bool(r["blind"]), "asked_at": r["asked_at"]}

    def save_answer(
        self, question_id: str, strategy_id: str, *,
        answer: Answer | None, error: str | None, trace: list[dict],
    ) -> None:
        trace_json = json.dumps(trace)
        if answer is None or error is not None:
            self._run(
                "INSERT OR REPLACE INTO answers(question_id, strategy, status, trace_json, error)"
                " VALUES(?,?,?,?,?)",
                (question_id, strategy_id, "failed", trace_json, error or "Unknown error"),
            )
            return
        d = answer_to_dict(answer)
        m, u = d["metrics"], d["metrics"]["usage"]
        self._run(
            "INSERT OR REPLACE INTO answers VALUES(?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?)",
            (question_id, strategy_id, d["status"], d["text"], json.dumps(d["citations"]), trace_json,
             m["latency_ms"], u["input_tokens"], u["output_tokens"], u["cache_read_tokens"],
             u["cache_write_tokens"], m["cost_usd"], json.dumps(m["manuals_used"]), m["tool_calls"]),
        )

    def answers_for(self, question_id: str) -> dict[str, dict]:
        rows = self._run("SELECT * FROM answers WHERE question_id=?", (question_id,))
        return {r["strategy"]: _answer_row(r) for r in rows}

    def all_answers(self) -> list[dict]:
        return [_answer_row(r) for r in self._run("SELECT * FROM answers ORDER BY rowid")]

    def upsert_vote(self, question_id: str, strategy_id: str, stars: int, blind: bool) -> None:
        if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
            raise VoteError("stars must be an integer between 1 and 5")
        if self.get_question(question_id) is None:
            raise VoteError("unknown question")
        rows = self._run(
            "SELECT error FROM answers WHERE question_id=? AND strategy=?", (question_id, strategy_id)
        )
        if not rows:
            raise VoteError(f"no answer for strategy {strategy_id!r}")
        if rows[0]["error"] is not None:
            raise VoteError("cannot vote on a failed answer")
        self._run(
            "INSERT INTO votes VALUES(?,?,?,?,?) ON CONFLICT(question_id, strategy) DO UPDATE SET"
            " stars=excluded.stars, blind=excluded.blind, voted_at=excluded.voted_at",
            (question_id, strategy_id, stars, int(blind), _now()),
        )

    def votes(self, mode: Literal["all", "blind", "labelled"] = "all") -> list[dict]:
        where = {"all": "", "blind": "WHERE blind=1", "labelled": "WHERE blind=0"}[mode]
        rows = self._run(f"SELECT * FROM votes {where} ORDER BY rowid")
        return [
            {"question_id": r["question_id"], "strategy": r["strategy"],
             "stars": r["stars"], "blind": bool(r["blind"])}
            for r in rows
        ]

    def reset_votes(self) -> None:
        self._run("DELETE FROM votes")

    def export_rows(self) -> list[dict]:
        rows = self._run(
            "SELECT q.text AS question_text, v.strategy, v.stars, v.blind, v.voted_at,"
            " a.status, a.latency_ms, a.cost_usd, a.input_tokens, a.output_tokens"
            " FROM votes v JOIN questions q ON q.id=v.question_id"
            " JOIN answers a ON a.question_id=v.question_id AND a.strategy=v.strategy"
            " ORDER BY v.rowid"
        )
        return [{**dict(r), "blind": bool(r["blind"])} for r in rows]
