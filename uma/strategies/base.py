"""Shared types and helpers for all retrieval strategies."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from uma.config import cost_usd
from uma.llm import LLM, Completed, LLMError, TextChunk, Usage

if TYPE_CHECKING:
    from uma.strategies.web_sources import WebSources

logger = logging.getLogger(__name__)

TRUNCATED = "The answer was cut off (max_tokens reached)."

Status = Literal["answered", "not_covered", "contradiction_found"]
_STATUSES: tuple[str, ...] = ("answered", "not_covered", "contradiction_found")


@dataclass(frozen=True)
class Citation:
    manual_id: str
    manual_title: str
    section_id: str
    heading_path: tuple[str, ...]
    cited_text: str
    kind: Literal["manual", "web"] = "manual"
    url: str | None = None


@dataclass
class Metrics:
    latency_ms: int
    usage: Usage
    cost_usd: float | None
    manuals_used: list[str]
    tool_calls: int = 0
    web_searches: int = 0


@dataclass
class Answer:
    text: str
    citations: list[Citation]
    status: Status
    metrics: Metrics


@dataclass
class TextDelta:
    text: str


@dataclass
class TraceStep:
    kind: str
    detail: dict = field(default_factory=dict)


@dataclass
class Final:
    answer: Answer


@dataclass
class Failed:
    message: str
    hint_doc: str | None = None


AnswerEvent = TextDelta | TraceStep | Final | Failed


class Strategy(Protocol):
    id: str
    title: str

    def answer(self, question: str) -> AsyncIterator[AnswerEvent]: ...


_OPEN = "<status>"
_CLOSE = "</status>"


class StatusTagFilter:
    """Hides a trailing <status>...</status> tag from streamed text."""

    def __init__(self) -> None:
        self._held = ""  # withheld text: a possible tag prefix, or the tag body
        self._in_tag = False
        self._done = False  # a complete tag has been consumed
        self._status: Status = "answered"
        self._found = False

    def feed(self, chunk: str) -> str:
        self._held += chunk
        out = ""
        while True:
            if self._in_tag:
                end = self._held.find(_CLOSE)
                if end < 0:
                    return out
                value = self._held[len(_OPEN) : end].strip()
                self._held = self._held[end + len(_CLOSE) :]
                self._in_tag = False
                self._done = True
                if value in _STATUSES:
                    self._status = value  # type: ignore[assignment]
                    self._found = True
                else:
                    self._status, self._found = "answered", False
                continue
            start = self._held.find(_OPEN)
            if start >= 0:
                out += self._held[:start]
                self._held = self._held[start:]
                self._in_tag = True
                continue
            keep = 0
            for n in range(min(len(_OPEN) - 1, len(self._held)), 0, -1):
                if _OPEN.startswith(self._held[-n:]):
                    keep = n
                    break
            cut = len(self._held) - keep
            if self._done:
                # hold trailing whitespace after the tag until more text follows
                cut = len(self._held[:cut].rstrip())
            out += self._held[:cut]
            self._held = self._held[cut:]
            return out

    def finish(self) -> tuple[str, Status, bool]:
        # An unterminated tag is not a tag: show what was withheld.
        rest, self._held = self._held, ""
        if self._done and not self._in_tag and not rest.strip():
            rest = ""  # trailing whitespace after the tag is discarded
        self._in_tag = False
        return rest, self._status, self._found


def warn_missing_status(strategy_id: str | None, log: logging.Logger | None = None) -> None:
    """Spec 5.3 / ADR 0009: a missing or malformed status tag yields answered plus a warning."""
    (log or logger).warning("Strategy %s: missing or malformed status tag; defaulting to answered",
                   strategy_id or "?")


def strip_status(text: str) -> tuple[str, Status, bool]:
    f = StatusTagFilter()
    shown = f.feed(text)
    rest, status, found = f.finish()
    return shown + rest, status, found


def _index_of(citation: Citation, cits: list[Citation]) -> int:
    for i, c in enumerate(cits):
        if c.section_id == citation.section_id:
            return i + 1
    cits.append(citation)
    return len(cits)


def assemble_cited_text(
    content: list[dict], resolve: Callable[[dict], Citation | None]
) -> tuple[str, list[Citation]]:
    parts: list[str] = []
    cits: list[Citation] = []
    for block in content:
        if block.get("type") != "text":
            continue
        parts.append(block.get("text", ""))
        markers = ""
        for raw in block.get("citations") or []:
            citation = resolve(raw)
            if citation is not None:
                markers += f"[{_index_of(citation, cits)}]"
        if markers:
            parts.append(" " + markers)
    return "".join(parts), cits


_MARKER = re.compile(r"\[§([^\]]+)\]")


def resolve_section_markers(
    text: str, lookup: Callable[[str], Citation | None]
) -> tuple[str, list[Citation]]:
    cits: list[Citation] = []

    def repl(m: re.Match[str]) -> str:
        citation = lookup(m.group(1))
        return "" if citation is None else f"[{_index_of(citation, cits)}]"

    return _MARKER.sub(repl, text), cits


_MIXED_MARKER = re.compile(r"\[(?:§([^\]]+)|web:(\d+))\]")


def resolve_mixed_markers(
    text: str, lookup: Callable[[str], Citation | None], sources: WebSources
) -> tuple[str, list[Citation]]:
    """One pass over [§id] and [web:n] markers, numbered together; unknown ones are removed."""
    cits: list[Citation] = []

    def repl(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            citation = lookup(m.group(1))
        else:
            citation = sources.citation(int(m.group(2)))
        return "" if citation is None else f"[{_index_of(citation, cits)}]"

    return _MIXED_MARKER.sub(repl, text), cits


def answer_to_dict(answer: Answer) -> dict:
    d = asdict(answer)
    for c in d["citations"]:
        c["heading_path"] = list(c["heading_path"])
    return d


async def run_single_call(
    llm: LLM,
    system: str,
    messages: list[dict],
    resolve: Callable[[dict], Citation | None],
    started: float,
    model: str,
    strategy_id: str | None = None,
) -> AsyncIterator[AnswerEvent]:
    """One streamed LLM call -> TextDelta* then Final (or Failed).

    `started` is a time.perf_counter() value taken by the caller (latency base);
    `model` selects the price for Metrics.cost_usd; `resolve` maps a raw citation
    dict to a Citation, or None if it cannot (see assemble_cited_text).
    The status tag is hidden from streamed text and parsed from the assembled text.
    LLMError is converted to Failed(str(e)); stop_reason "refusal" or "max_tokens" to Failed.
    `strategy_id` only labels the warning logged for a missing status tag.
    """
    filt = StatusTagFilter()
    try:
        async for event in llm.stream(system=system, messages=messages):
            if isinstance(event, TextChunk):
                shown = filt.feed(event.text)
                if shown:
                    yield TextDelta(shown)
            elif isinstance(event, Completed):
                response = event.response
                if response.stop_reason == "refusal":
                    yield Failed("The model declined this question")
                    return
                if response.stop_reason == "max_tokens":
                    yield Failed(TRUNCATED)
                    return
                raw, citations = assemble_cited_text(response.content, resolve)
                text, status, found = strip_status(raw)
                if not found:
                    warn_missing_status(strategy_id)
                rest, _, _ = filt.finish()
                if rest:
                    yield TextDelta(rest)
                u = response.usage
                metrics = Metrics(
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    usage=u,
                    cost_usd=cost_usd(model, u.input_tokens, u.output_tokens,
                                      u.cache_read_tokens, u.cache_write_tokens),
                    manuals_used=list(dict.fromkeys(c.manual_title for c in citations)),
                )
                yield Final(Answer(text, citations, status, metrics))
                return
    except LLMError as e:
        yield Failed(str(e))
