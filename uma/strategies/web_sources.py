"""Numbered web sources collected during an agentic run."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from uma.strategies.base import Citation

_WEB_URL_MARKER = re.compile(r"\[web:([^\]\s]+)\]")


class WebSources:
    """Registry of web pages, numbered 1.. in the order they were first seen."""

    def __init__(self) -> None:
        self._order: list[tuple[str, str]] = []  # (url, title)
        self._numbers: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._order)

    def add(self, url: str, title: str) -> int:
        existing = self._numbers.get(url)
        if existing is not None:
            return existing
        self._order.append((url, title))
        self._numbers[url] = len(self._order)
        return len(self._order)

    def number(self, url: str) -> int | None:
        return self._numbers.get(url)

    def citation(self, n: int) -> Citation | None:
        if not 1 <= n <= len(self._order):
            return None
        url, title = self._order[n - 1]
        return Citation(
            manual_id=urlparse(url).hostname or url,
            manual_title=title,
            section_id=url,
            heading_path=(),
            cited_text="",
            kind="web",
            url=url,
        )

    def listing(self) -> str:
        return "\n".join(
            f"[web:{i}] {title} — {url}" for i, (url, title) in enumerate(self._order, 1)
        )

    def rewrite(self, notes: str) -> str:
        """Turn [web:<url>] into [web:<n>]; drop markers whose URL is unknown."""

        def repl(m: re.Match[str]) -> str:
            url = m.group(1)
            if url.isdigit():
                return m.group(0)
            n = self._numbers.get(url)
            return "" if n is None else f"[web:{n}]"

        return _WEB_URL_MARKER.sub(repl, notes)
