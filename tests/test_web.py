import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import uma.llm
from uma.config import Settings
from uma.corpus.ingest import ingest
from uma.corpus.store import CorpusStore
from uma.embedding import HashingEmbedder
from uma.llm import AnthropicLLM, FakeLLM, text_response
from uma.web import STRATEGY_ORDER, create_app

SAMPLE = Path(__file__).resolve().parent.parent / "sample_manuals"
ANSWER = "Hold the button.\n<status>answered</status>"


def make_client(tmp_path, *, ingest_sample=True, llm=None):
    settings = Settings(db_path=tmp_path / "uma.db")
    emb = HashingEmbedder()
    if ingest_sample:
        ingest(SAMPLE, CorpusStore(settings.db_path), emb)
    llm = llm or FakeLLM([text_response(ANSWER) for _ in range(3)])
    return TestClient(create_app(settings, llm=llm, embedder=emb)), llm


@pytest.fixture
def client_with_fake_llm(tmp_path):
    return make_client(tmp_path)


def ask(client, text="How do I pair?", blind=False):
    return client.post("/api/questions", json={"text": text, "blind": blind}).json()["question_id"]


def stream(client, qid):
    with client.stream("GET", f"/api/questions/{qid}/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


def finals(payloads):
    return {p["strategy"]: p for p in payloads if p["type"] in ("final", "failed")}


def test_ask_and_stream(client_with_fake_llm):
    client, _ = client_with_fake_llm
    payloads = stream(client, ask(client))
    assert payloads[-1] == {"type": "done"}
    assert set(finals(payloads)) == set(STRATEGY_ORDER)


def test_stream_replay_does_not_rerun(client_with_fake_llm):
    client, llm = client_with_fake_llm
    qid = ask(client)
    first = stream(client, qid)
    calls = len(llm.calls)
    second = stream(client, qid)
    assert len(llm.calls) == calls
    assert set(finals(first)) == set(finals(second)) == set(STRATEGY_ORDER)
    assert finals(first) == finals(second)
    assert second[-1] == {"type": "done"}


class BlockingLLM(FakeLLM):
    def __init__(self, responses, gate):
        super().__init__(responses)
        self.gate = gate

    async def stream(self, **kw):
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        async for ev in super().stream(**kw):
            yield ev


def test_concurrent_stream_returns_409_then_replays(tmp_path):
    gate = threading.Event()
    client, llm = make_client(tmp_path, llm=BlockingLLM([text_response(ANSWER) for _ in range(3)], gate))
    qid = ask(client)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("p", stream(client, qid)))
    t.start()
    for _ in range(500):
        if qid in client.app.state.running:
            break
        time.sleep(0.01)
    assert client.get(f"/api/questions/{qid}/stream").status_code == 409
    gate.set()
    t.join(timeout=10)
    assert result["p"][-1] == {"type": "done"}
    calls = len(llm.calls)
    again = stream(client, qid)
    assert len(llm.calls) == calls and again[-1] == {"type": "done"}


def test_partial_answers_run_only_missing_strategies(client_with_fake_llm):
    client, llm = client_with_fake_llm
    qid = ask(client)
    client.app.state.log.save_answer(qid, "rag", answer=None, error="boom", trace=[])
    payloads = stream(client, qid)
    f = finals(payloads)
    assert set(f) == set(STRATEGY_ORDER) and payloads[-1] == {"type": "done"}
    assert f["rag"]["type"] == "failed" and f["rag"]["message"] == "boom"
    assert llm.calls  # the other two strategies actually ran
    assert len(llm.calls) == 2
    assert set(client.app.state.log.answers_for(qid)) == set(STRATEGY_ORDER)


def test_swagger_does_not_shadow_docs_mount(client_with_fake_llm):
    client, _ = client_with_fake_llm
    assert client.get("/api/docs").status_code == 200


def test_stream_releases_running_guard(client_with_fake_llm):
    client, _ = client_with_fake_llm
    qid = ask(client)
    stream(client, qid)
    assert qid not in client.app.state.running


def test_unknown_stream_404(client_with_fake_llm):
    client, _ = client_with_fake_llm
    assert client.get("/api/questions/nope/stream").status_code == 404


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_question_422(client_with_fake_llm, text):
    client, _ = client_with_fake_llm
    assert client.post("/api/questions", json={"text": text, "blind": False}).status_code == 422


def test_empty_corpus_409(tmp_path):
    client, _ = make_client(tmp_path, ingest_sample=False)
    r = client.post("/api/questions", json={"text": "hi", "blind": False})
    assert r.status_code == 409
    assert r.json() == {"detail": "No manuals ingested. Run: uv run python -m uma ingest"}
    assert client.get("/api/status").json()["corpus_ready"] is False


def test_post_vote_invalid_returns_400(client_with_fake_llm):
    client, _ = client_with_fake_llm
    qid = ask(client)
    stream(client, qid)
    r = client.post("/api/votes", json={"question_id": qid, "strategy": "rag", "stars": 6, "blind": False})
    assert r.status_code == 400 and r.json()["detail"]
    client.app.state.log.save_answer(qid, "rag", answer=None, error="boom", trace=[])
    r = client.post("/api/votes", json={"question_id": qid, "strategy": "rag", "stars": 3, "blind": False})
    assert r.status_code == 400 and "failed" in r.json()["detail"]


def test_vote_then_leaderboard(client_with_fake_llm):
    client, _ = client_with_fake_llm
    qid = ask(client)
    stream(client, qid)
    r = client.post("/api/votes", json={"question_id": qid, "strategy": "rag", "stars": 5, "blind": False})
    assert r.status_code == 204
    data = client.get("/api/leaderboard").json()
    rows = {row["strategy_id"]: row for row in data["rows"]}
    assert rows["rag"]["votes"] == 1 and rows["rag"]["avg_stars"] == 5
    assert data["recent"][0]["question_id"] == qid
    blind = client.get("/api/leaderboard?mode=blind").json()
    assert all(row["votes"] == 0 for row in blind["rows"]) and blind["recent"] == []
    assert client.get("/api/leaderboard?mode=bogus").status_code == 422
    assert client.post("/api/reset-votes").status_code == 204
    assert all(r["votes"] == 0 for r in client.get("/api/leaderboard").json()["rows"])


def test_export_csv_header(client_with_fake_llm):
    client, _ = client_with_fake_llm
    qid = ask(client)
    stream(client, qid)
    client.post("/api/votes", json={"question_id": qid, "strategy": "rag", "stars": 4, "blind": True})
    r = client.get("/api/export.csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "uma-votes.csv" in r.headers["content-disposition"]
    lines = r.text.splitlines()
    assert lines[0].startswith("question_text,strategy,stars,blind")
    assert len(lines) == 2


def test_export_csv_empty_still_has_header(client_with_fake_llm):
    client, _ = client_with_fake_llm
    assert client.get("/api/export.csv").text.splitlines()[0].startswith("question_text,strategy,stars,blind")


def test_section_endpoint(client_with_fake_llm):
    client, _ = client_with_fake_llm
    sec = CorpusStore(client.app.state.settings.db_path).sections()[0]
    d = client.get(f"/api/sections/{sec.id}").json()
    assert set(d) == {"id", "manual_title", "heading_path", "text", "source_url"}
    assert d["id"] == sec.id and d["text"] == sec.text
    assert client.get("/api/sections/missing").status_code == 404


def test_strategies_status_and_static(client_with_fake_llm):
    client, _ = client_with_fake_llm
    s = client.get("/api/strategies").json()
    assert [x["id"] for x in s] == STRATEGY_ORDER
    assert s[1]["flow"] == "/static/diagrams/rag-flow.mmd"
    assert s[1]["sequence"] == "/static/diagrams/rag-sequence.mmd"
    assert s[2]["doc"] == "/docs/strategies/3-agentic.md"
    st = client.get("/api/status").json()
    assert st["corpus_ready"] and len(st["manuals"]) == 3 and st["model"]
    assert set(st["manuals"][0]) == {"id", "title", "sections"}
    assert client.get("/").status_code == 200
    assert client.get("/leaderboard").status_code == 200


def test_missing_api_key_each_column_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(uma.llm, "credentials_available", lambda: False)
    settings = Settings(db_path=tmp_path / "uma.db")
    emb = HashingEmbedder()
    ingest(SAMPLE, CorpusStore(settings.db_path), emb)
    client = TestClient(create_app(settings, llm=AnthropicLLM(settings), embedder=emb))
    payloads = stream(client, ask(client))
    failed = [p for p in payloads if p["type"] == "failed"]
    assert {p["strategy"] for p in failed} == set(STRATEGY_ORDER)
    assert all("ANTHROPIC_API_KEY" in p["message"] for p in failed)
    assert payloads[-1] == {"type": "done"}
