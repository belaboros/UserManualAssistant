"""Runtime settings and token cost calculation."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model: str = "claude-sonnet-5-5"
    effort: str = "medium"
    db_path: Path = Path("data/uma.db")
    manuals_dir: Path = Path("manuals")
    whole_context_max_tokens: int = 800_000
    rag_top_k: int = 8
    agent_max_tool_calls: int = 8
    strategy_timeout_s: float = 90.0
    agent_web_local_max_tool_calls: int = 8
    agent_web_max_searches: int = 8
    agent_web_timeout_s: float = 180.0


# Anthropic web search tool price: USD per search.
WEB_SEARCH_USD_PER_SEARCH: float = 0.01


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    d = Settings()
    return Settings(
        model=env.get("UMA_MODEL", d.model),
        effort=env.get("UMA_EFFORT", d.effort),
        db_path=Path(env.get("UMA_DB_PATH", d.db_path)),
        manuals_dir=Path(env.get("UMA_MANUALS_DIR", d.manuals_dir)),
        whole_context_max_tokens=int(env.get("WHOLE_CONTEXT_MAX_TOKENS", d.whole_context_max_tokens)),
        rag_top_k=int(env.get("RAG_TOP_K", d.rag_top_k)),
        agent_max_tool_calls=int(env.get("AGENT_MAX_TOOL_CALLS", d.agent_max_tool_calls)),
        strategy_timeout_s=float(env.get("STRATEGY_TIMEOUT_S", d.strategy_timeout_s)),
        agent_web_local_max_tool_calls=int(
            env.get("AGENT_WEB_LOCAL_MAX_TOOL_CALLS", d.agent_web_local_max_tool_calls)),
        agent_web_max_searches=int(env.get("AGENT_WEB_MAX_SEARCHES", d.agent_web_max_searches)),
        agent_web_timeout_s=float(env.get("AGENT_WEB_TIMEOUT_S", d.agent_web_timeout_s)),
    )


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


# Prices come from Anthropic's pricing as of 2026-09.
PRICES: dict[str, Price] = {
    "claude-sonnet-5-5": Price(2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": Price(4.00, 20.00, 0.20, 5.00),
}


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Cost in USD, or None when the model has no known price."""
    p = PRICES.get(model)
    if p is None:
        return None
    return (
        input_tokens * p.input
        + output_tokens * p.output
        + cache_read_tokens * p.cache_read
        + cache_write_tokens * p.cache_write
    ) / 1_000_000
