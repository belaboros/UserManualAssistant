"""FastAPI app: question streaming over SSE, votes, leaderboard and static pages."""

import csv
import io
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from uma.config import Settings
from uma.corpus.store import CorpusStore
from uma.embedding import Embedder, FastEmbedEmbedder
from uma.leaderboard import compute_leaderboard, recent_questions
from uma.llm import LLM, AnthropicLLM
from uma.log import Log, VoteError
from uma.runner import run_question
from uma.strategies.agentic import AgenticStrategy
from uma.strategies.rag import RagStrategy
from uma.strategies.whole_context import WholeContextStrategy

STRATEGY_ORDER = ["whole_context", "rag", "agentic"]
_DOCS = {
    "whole_context": "/docs/strategies/1-whole-context.md",
    "rag": "/docs/strategies/2-rag.md",
    "agentic": "/docs/strategies/3-agentic.md",
}
_PKG = Path(__file__).resolve().parent
_STATIC = _PKG / "static"
_REPO_DOCS = _PKG.parent / "docs"
_CSV_FIELDS = [
    "question_text", "strategy", "stars", "blind", "voted_at",
    "status", "latency_ms", "cost_usd", "input_tokens", "output_tokens",
]
_NO_MANUALS = "No manuals ingested. Run: uv run python -m uma ingest"


class QuestionIn(BaseModel):
    text: str
    blind: bool = False


class VoteIn(BaseModel):
    question_id: str
    strategy: str
    stars: int
    blind: bool = False


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _replay(stored: dict[str, dict]) -> list[dict]:
    out = []
    for sid in STRATEGY_ORDER:
        a = stored.get(sid)
        if a is None:
            continue
        if a["status"] == "failed":
            out.append({"strategy": sid, "type": "failed", "message": a["error"], "hint_doc": None})
        else:
            out.append({"strategy": sid, "type": "final", "answer": a["answer"]})
    return out + [{"type": "done"}]


def create_app(
    settings: Settings, *, llm: LLM | None = None, embedder: Embedder | None = None
) -> FastAPI:
    llm = llm or AnthropicLLM(settings)
    embedder = embedder or FastEmbedEmbedder()  # loads its model lazily on first search
    store = CorpusStore(settings.db_path)
    log = Log(settings.db_path)
    strategies = {
        s.id: s
        for s in (
            WholeContextStrategy(store, llm, settings),
            RagStrategy(store, embedder, llm, settings),
            AgenticStrategy(store, embedder, llm, settings),
        )
    }
    ordered = [strategies[i] for i in STRATEGY_ORDER]

    app = FastAPI(title="UserManualAssistant")
    app.state.settings, app.state.log, app.state.store = settings, log, store
    # Question ids whose strategies are running now. A concurrent second stream request for
    # the same id gets 409 rather than a second run (or a partial replay).
    app.state.running = set()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/leaderboard")
    def leaderboard_page() -> FileResponse:
        return FileResponse(_STATIC / "leaderboard.html")

    @app.get("/api/strategies")
    def api_strategies() -> list[dict]:
        return [
            {
                "id": i, "title": strategies[i].title,
                "flow": f"/static/diagrams/{i}-flow.mmd",
                "sequence": f"/static/diagrams/{i}-sequence.mmd",
                "doc": _DOCS[i],
            }
            for i in STRATEGY_ORDER
        ]

    @app.get("/api/status")
    def api_status() -> dict:
        manuals = store.manuals()
        return {
            "corpus_ready": not store.is_empty(),
            "manuals": [
                {"id": m.meta.id, "title": m.meta.title, "sections": m.section_count} for m in manuals
            ],
            "model": settings.model,
        }

    @app.post("/api/questions")
    def api_ask(body: QuestionIn) -> dict:
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "Question text must not be empty")
        if store.is_empty():
            raise HTTPException(409, _NO_MANUALS)
        return {"question_id": log.create_question(text, body.blind)}

    @app.get("/api/questions/{question_id}/stream")
    def api_stream(question_id: str) -> StreamingResponse:
        question = log.get_question(question_id)
        if question is None:
            raise HTTPException(404, "Unknown question")
        if question_id in app.state.running:
            raise HTTPException(409, "This question is already running")
        stored = log.answers_for(question_id)
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

        if stored:
            async def replay() -> AsyncIterator[str]:
                for p in _replay(stored):
                    yield _sse(p)

            return StreamingResponse(replay(), media_type="text/event-stream", headers=headers)

        app.state.running.add(question_id)

        async def live() -> AsyncIterator[str]:
            try:
                async for p in run_question(
                    question_id, question["text"], ordered, log, settings.strategy_timeout_s
                ):
                    yield _sse(p)
            finally:
                app.state.running.discard(question_id)

        return StreamingResponse(live(), media_type="text/event-stream", headers=headers)

    @app.get("/api/sections/{section_id}")
    def api_section(section_id: str) -> dict:
        s = store.section(section_id)
        if s is None:
            raise HTTPException(404, "Unknown section")
        titles = {m.meta.id: m.meta.title for m in store.manuals()}
        return {
            "id": s.id, "manual_title": titles.get(s.manual_id, s.manual_id),
            "heading_path": list(s.heading_path), "text": s.text, "source_url": s.source_url,
        }

    @app.post("/api/votes", status_code=204)
    def api_vote(body: VoteIn) -> Response:
        try:
            log.upsert_vote(body.question_id, body.strategy, body.stars, body.blind)
        except VoteError as e:
            raise HTTPException(400, str(e)) from e
        return Response(status_code=204)

    @app.get("/api/leaderboard")
    def api_leaderboard(mode: Literal["all", "blind", "labelled"] = "all") -> dict:
        titles = {s.id: s.title for s in ordered}
        rows = compute_leaderboard(log, titles, mode)
        return {"rows": [asdict(r) for r in rows], "recent": recent_questions(log, mode)}

    @app.get("/api/export.csv")
    def api_export() -> Response:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(log.export_rows())
        return Response(
            buf.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="uma-votes.csv"'},
        )

    @app.post("/api/reset-votes", status_code=204)
    def api_reset() -> Response:
        log.reset_votes()
        return Response(status_code=204)

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
    if _REPO_DOCS.is_dir():
        app.mount("/docs", StaticFiles(directory=_REPO_DOCS), name="docs")
    return app
