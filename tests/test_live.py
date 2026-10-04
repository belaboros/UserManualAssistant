"""Opt-in smoke test against the real Claude API: `uv run pytest -m live -v`."""

from pathlib import Path

import pytest

from uma.config import Settings
from uma.corpus.ingest import ingest
from uma.corpus.store import CorpusStore
from uma.embedding import FastEmbedEmbedder
from uma.llm import AnthropicLLM, credentials_available
from uma.log import Log
from uma.runner import run_question
from uma.strategies.agentic import AgenticStrategy
from uma.strategies.rag import RagStrategy
from uma.strategies.whole_context import WholeContextStrategy

SAMPLE = Path(__file__).resolve().parent.parent / "sample_manuals"
QUESTION = "How long do I hold the reset button to factory-reset the thermostat?"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not credentials_available(), reason="no ANTHROPIC_API_KEY or `ant` auth profile"),
]


async def test_all_strategies_answer_and_flag_the_reset_contradiction(tmp_path):
    settings = Settings(db_path=tmp_path / "uma.db", strategy_timeout_s=180.0)
    store = CorpusStore(settings.db_path)
    embedder = FastEmbedEmbedder()
    ingest(SAMPLE, store, embedder)
    llm = AnthropicLLM(settings)
    log = Log(settings.db_path)
    strategies = [
        WholeContextStrategy(store, llm, settings),
        RagStrategy(store, embedder, llm, settings),
        AgenticStrategy(store, embedder, llm, settings),
    ]
    qid = log.create_question(QUESTION, blind=False)

    finals: dict[str, dict] = {}
    async for ev in run_question(qid, QUESTION, strategies, log, timeout_s=180.0):
        if ev["type"] == "failed":
            pytest.fail(f"{ev['strategy']} failed: {ev['message']}")
        if ev["type"] == "final":
            finals[ev["strategy"]] = ev["answer"]

    assert set(finals) == {s.id for s in strategies}
    statuses = {sid: a["status"] for sid, a in finals.items()}
    assert "contradiction_found" in statuses.values(), statuses
