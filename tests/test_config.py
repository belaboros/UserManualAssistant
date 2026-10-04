from pathlib import Path

import pytest

from uma.config import cost_usd, load_settings


def test_defaults():
    s = load_settings({})
    assert s.model == "claude-sonnet-5-5" and s.effort == "medium"
    assert s.whole_context_max_tokens == 800_000 and s.rag_top_k == 8
    assert s.agent_max_tool_calls == 8 and s.strategy_timeout_s == 90.0


def test_env_overrides():
    s = load_settings({"UMA_MODEL": "claude-opus-5-5", "RAG_TOP_K": "5", "UMA_DB_PATH": "/tmp/x.db"})
    assert s.model == "claude-opus-5-5" and s.rag_top_k == 5 and s.db_path == Path("/tmp/x.db")


def test_cost_sonnet():
    # 1M input @ $2, 100k output @ $10, 1M cache read @ $0.20, 100k cache write @ $2.50
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 100_000, 1_000_000, 100_000) == pytest.approx(2.0 + 1.0 + 0.2 + 0.25)


def test_cost_unknown_model_is_none():
    assert cost_usd("mystery-model", 10, 10) is None


def test_agent_web_defaults_and_env():
    s = load_settings({})
    assert (s.agent_web_local_max_tool_calls, s.agent_web_max_searches, s.agent_web_timeout_s) == (8, 8, 180.0)
    s = load_settings({"AGENT_WEB_LOCAL_MAX_TOOL_CALLS": "3", "AGENT_WEB_MAX_SEARCHES": "2",
                       "AGENT_WEB_TIMEOUT_S": "60"})
    assert (s.agent_web_local_max_tool_calls, s.agent_web_max_searches, s.agent_web_timeout_s) == (3, 2, 60.0)
