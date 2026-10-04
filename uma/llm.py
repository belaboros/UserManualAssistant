"""Async Claude wrapper shared by all retrieval strategies, plus a scripted FakeLLM for tests."""

from __future__ import annotations

import asyncio
import copy
import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import anthropic

from uma.config import Settings


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        if not isinstance(other, Usage):
            return NotImplemented
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass
class LLMResponse:
    content: list[dict]
    stop_reason: str
    usage: Usage


@dataclass
class TextChunk:
    text: str


@dataclass
class Completed:
    response: LLMResponse


class LLMError(Exception):
    """Carries a user-facing message."""


class LLM(Protocol):
    def stream(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[TextChunk | Completed]: ...

    async def count_tokens(self, *, system: str, messages: list[dict]) -> int: ...


MISSING_KEY_MESSAGE = "ANTHROPIC_API_KEY is not set. Add it to .env and restart."
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def credentials_available() -> bool:
    """True if an API key is set, or the `ant` CLI has an active auth profile."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        result = subprocess.run(["ant", "auth", "status"], capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _to_llm_error(exc: anthropic.APIError) -> LLMError:
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY in .env and restart.")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("Anthropic rate limit reached. Wait a moment and try again.")
    if isinstance(exc, anthropic.APIStatusError):
        return LLMError(f"Anthropic API error ({exc.status_code}): {exc.message}")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("Could not reach the Anthropic API. Check your network connection and try again.")
    return LLMError(f"Anthropic API error: {exc}")


class AnthropicLLM:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self._client = client

    async def _get_client(self):
        if self._client is None:
            # May spawn `ant auth status`; keep it off the event loop. Checked once, at client creation.
            if not await asyncio.to_thread(credentials_available):
                raise LLMError(MISSING_KEY_MESSAGE)
            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def stream(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[TextChunk | Completed]:
        client = await self._get_client()
        kwargs: dict = {
            "model": self.settings.model,
            "max_tokens": 16000,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.settings.effort},
            "betas": [FALLBACK_BETA],
            "extra_body": {"fallbacks": "default"},
            "cache_control": {"type": "ephemeral"},
        }
        if tools is not None:
            kwargs["tools"] = tools
        try:
            async with client.beta.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield TextChunk(text)
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise _to_llm_error(exc) from exc
        # With a server-side fallback, top-level usage covers only the attempt that produced this message.
        u = final.usage
        yield Completed(
            LLMResponse(
                content=[b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in final.content],
                stop_reason=final.stop_reason,
                usage=Usage(
                    u.input_tokens,
                    u.output_tokens,
                    getattr(u, "cache_read_input_tokens", 0) or 0,
                    getattr(u, "cache_creation_input_tokens", 0) or 0,
                ),
            )
        )

    async def count_tokens(self, *, system: str, messages: list[dict]) -> int:
        client = await self._get_client()
        try:
            result = await client.messages.count_tokens(
                model=self.settings.model, system=system, messages=messages
            )
        except anthropic.APIError as exc:
            raise _to_llm_error(exc) from exc
        return result.input_tokens


class FakeLLM:
    """Scripted LLM for tests. Never mutates `.responses`; yields copies."""

    def __init__(self, responses: list[LLMResponse], token_count: int = 1_000):
        self.responses = responses
        self.token_count = token_count
        self.calls: list[dict] = []
        self._next = 0

    async def stream(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[TextChunk | Completed]:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if self._next >= len(self.responses):
            raise AssertionError("FakeLLM ran out of scripted responses")
        response = copy.deepcopy(self.responses[self._next])
        self._next += 1
        for block in response.content:
            if block.get("type") == "text":
                text = block["text"]
                mid = len(text) // 2
                yield TextChunk(text[:mid])
                yield TextChunk(text[mid:])
        yield Completed(response)

    async def count_tokens(self, *, system: str, messages: list[dict]) -> int:
        return self.token_count


def text_response(text: str, citations: list[dict] | None = None, usage: Usage | None = None) -> LLMResponse:
    block: dict = {"type": "text", "text": text}
    if citations is not None:
        block["citations"] = citations
    return LLMResponse([block], "end_turn", usage if usage is not None else Usage(10, 5))


def tool_use_response(
    name: str, input: dict, id: str | None = None, usage: Usage | None = None
) -> LLMResponse:
    block = {"type": "tool_use", "id": id or f"toolu_{uuid.uuid4().hex[:16]}", "name": name, "input": input}
    return LLMResponse([block], "tool_use", usage if usage is not None else Usage(10, 5))


def finish_phase_response(
    sufficient: bool, gaps: list[str], notes: str, *, extra: list[dict] | None = None
) -> LLMResponse:
    """A `tool_use` turn calling finish_phase; `extra` blocks come before it."""
    block = tool_use_response("finish_phase", {"sufficient": sufficient, "gaps": gaps, "notes": notes}).content[0]
    return LLMResponse([*(extra or []), block], "tool_use", Usage(10, 5))


def web_search_blocks(
    query: str, results: list[tuple[str, str]] | None, *, error_code: str | None = None, id: str | None = None
) -> list[dict]:
    """A server-side web search: its `server_tool_use` block and the matching `web_search_tool_result`.

    `results` are (url, title) pairs; pass `error_code` (with `results=None`) for a failed search.
    """
    block_id = id or f"srvtoolu_{uuid.uuid4().hex[:16]}"
    if error_code is not None:
        content: list[dict] | dict = {"type": "web_search_tool_result_error", "error_code": error_code}
    else:
        content = [{"type": "web_search_result", "url": url, "title": title} for url, title in results or []]
    return [
        {"type": "server_tool_use", "id": block_id, "name": "web_search", "input": {"query": query}},
        {"type": "web_search_tool_result", "tool_use_id": block_id, "content": content},
    ]


def pause_turn_response(blocks: list[dict]) -> LLMResponse:
    """A turn the API paused mid-way (long-running server tools); resumed by calling again."""
    return LLMResponse(list(blocks), "pause_turn", Usage(10, 5))
