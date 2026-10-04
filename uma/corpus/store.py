"""SQLite corpus store: manuals, sections, chunks (with embeddings) and FTS5 index."""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

from uma.corpus.models import Chunk, ManualMeta, ManualRecord, Section

_SCHEMA = """
CREATE TABLE IF NOT EXISTS manuals(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
  visibility TEXT NOT NULL, base_url TEXT, token_count INTEGER);
CREATE TABLE IF NOT EXISTS sections(
  id TEXT PRIMARY KEY, manual_id TEXT NOT NULL, doc_path TEXT NOT NULL,
  heading_path TEXT NOT NULL, anchor TEXT NOT NULL, text TEXT NOT NULL,
  position INTEGER NOT NULL, source_url TEXT);
CREATE TABLE IF NOT EXISTS chunks(
  id TEXT PRIMARY KEY, section_id TEXT NOT NULL, manual_id TEXT NOT NULL,
  text TEXT NOT NULL, position INTEGER NOT NULL, embedding BLOB NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, chunk_id UNINDEXED, manual_id UNINDEXED);
CREATE TABLE IF NOT EXISTS corpus_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_FTS_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}


def _fts_query(query: str) -> str:
    tokens = [t for t in re.findall(r"\w+", query) if t.upper() not in _FTS_KEYWORDS]
    return " OR ".join(f'"{t}"' for t in tokens)


def _section(r: sqlite3.Row) -> Section:
    return Section(
        id=r["id"], manual_id=r["manual_id"], doc_path=r["doc_path"],
        heading_path=tuple(json.loads(r["heading_path"])), anchor=r["anchor"],
        text=r["text"], position=r["position"], source_url=r["source_url"],
    )


class CorpusStore:
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

    def reset(self) -> None:
        with closing(self._conn()) as c, c:
            for t in ("manuals", "sections", "chunks", "chunks_fts", "corpus_meta"):
                c.execute(f"DELETE FROM {t}")

    def add_manual(self, meta: ManualMeta) -> None:
        self._run(
            "INSERT OR REPLACE INTO manuals(id,title,owner,visibility,base_url) VALUES(?,?,?,?,?)",
            (meta.id, meta.title, meta.owner, meta.visibility, meta.base_url),
        )

    def add_sections(self, sections: list[Section]) -> None:
        with closing(self._conn()) as c, c:
            c.executemany(
                "INSERT INTO sections VALUES(?,?,?,?,?,?,?,?)",
                [(s.id, s.manual_id, s.doc_path, json.dumps(list(s.heading_path)), s.anchor,
                  s.text, s.position, s.source_url) for s in sections],
            )

    def add_chunks(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings differ in length")
        with closing(self._conn()) as c, c:
            for ch, emb in zip(chunks, embeddings, strict=True):
                c.execute(
                    "INSERT INTO chunks VALUES(?,?,?,?,?,?)",
                    (ch.id, ch.section_id, ch.manual_id, ch.text, ch.position,
                     emb.astype(np.float32).tobytes()),
                )
                c.execute(
                    "INSERT INTO chunks_fts(text,chunk_id,manual_id) VALUES(?,?,?)",
                    (ch.text, ch.id, ch.manual_id),
                )

    def manuals(self) -> list[ManualRecord]:
        rows = self._run(
            "SELECT m.*, (SELECT COUNT(*) FROM sections s WHERE s.manual_id=m.id) AS n "
            "FROM manuals m ORDER BY m.id"
        )
        return [
            ManualRecord(
                meta=ManualMeta(r["id"], r["title"], r["owner"], r["visibility"], r["base_url"]),
                section_count=r["n"], token_count=r["token_count"],
            )
            for r in rows
        ]

    def sections(self, manual_id: str | None = None) -> list[Section]:
        if manual_id is None:
            rows = self._run("SELECT * FROM sections ORDER BY manual_id, position")
        else:
            rows = self._run("SELECT * FROM sections WHERE manual_id=? ORDER BY manual_id, position",
                             (manual_id,))
        return [_section(r) for r in rows]

    def section(self, section_id: str) -> Section | None:
        rows = self._run("SELECT * FROM sections WHERE id=?", (section_id,))
        return _section(rows[0]) if rows else None

    def chunk(self, chunk_id: str) -> Chunk:
        rows = self._run("SELECT * FROM chunks WHERE id=?", (chunk_id,))
        if not rows:
            raise KeyError(chunk_id)
        r = rows[0]
        return Chunk(r["id"], r["section_id"], r["manual_id"], r["text"], r["position"])

    def chunk_matrix(self) -> tuple[list[str], np.ndarray]:
        rows = self._run("SELECT id, embedding FROM chunks ORDER BY manual_id, section_id, position")
        ids = [r["id"] for r in rows]
        if not rows:
            return ids, np.zeros((0, 0), dtype=np.float32)
        return ids, np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])

    def fts_search(self, query: str, limit: int, manual_id: str | None = None) -> list[tuple[str, float]]:
        q = _fts_query(query)
        if not q:
            return []
        sql = "SELECT chunk_id, bm25(chunks_fts) AS score FROM chunks_fts WHERE chunks_fts MATCH ?"
        params: list = [q]
        if manual_id is not None:
            sql += " AND manual_id = ?"
            params.append(manual_id)
        sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
        params.append(limit)
        return [(r["chunk_id"], r["score"]) for r in self._run(sql, tuple(params))]

    def set_token_count(self, manual_id: str | None, n: int) -> None:
        if manual_id is None:
            self._run("INSERT OR REPLACE INTO corpus_meta(key,value) VALUES('token_count',?)", (str(n),))
        else:
            self._run("UPDATE manuals SET token_count=? WHERE id=?", (n, manual_id))

    def corpus_token_count(self) -> int | None:
        rows = self._run("SELECT value FROM corpus_meta WHERE key='token_count'")
        return int(rows[0]["value"]) if rows else None

    def is_empty(self) -> bool:
        return self._run("SELECT COUNT(*) AS n FROM chunks")[0]["n"] == 0
