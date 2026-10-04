"""Manual tools shared by the tool-using strategies: list, search and read the manuals."""

from __future__ import annotations

from uma.corpus.store import CorpusStore
from uma.embedding import Embedder
from uma.search import hybrid_search
from uma.strategies.base import Citation

MANUAL_TOOLS: list[dict] = [
    {
        "name": "list_manuals",
        "description": "List every manual: id, title, owner and number of sections.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "search",
        "description": (
            "Search the manuals. Returns up to 8 lines: section_id | manual title | heading path | "
            "excerpt. Optionally restrict to one manual by id (null searches all manuals)."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "manual_id": {"type": ["string", "null"]}},
            "required": ["query", "manual_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_section",
        "description": "Read the full text of one section by its section_id.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"section_id": {"type": "string"}},
            "required": ["section_id"],
            "additionalProperties": False,
        },
    },
]


class ToolError(Exception):
    """A tool failure reported back to the model as an is_error result."""


class ManualTools:
    def __init__(self, store: CorpusStore, embedder: Embedder) -> None:
        self.store, self.embedder = store, embedder

    @property
    def _titles(self) -> dict[str, str]:
        # Read per use so manuals ingested while the server runs are picked up.
        return {m.meta.id: m.meta.title for m in self.store.manuals()}

    def run(self, name: str, tool_input: object) -> str:
        args = tool_input if isinstance(tool_input, dict) else {}
        if name == "list_manuals":
            return "\n".join(
                f"{m.meta.id} | {m.meta.title} | {m.meta.owner} | {m.section_count} sections"
                for m in self.store.manuals()
            )
        if name == "search":
            query, manual_id = args.get("query"), args.get("manual_id")
            if not isinstance(query, str) or not (manual_id is None or isinstance(manual_id, str)):
                raise ToolError("search needs query (string) and manual_id (string or null)")
            hits = hybrid_search(self.store, self.embedder, query, k=8, manual_id=manual_id)
            if not hits:
                return "No results."
            return "\n".join(
                f"{h.section.id} | {self._titles.get(h.chunk.manual_id, h.chunk.manual_id)} | "
                f"{' › '.join(h.section.heading_path)} | {' '.join(h.chunk.text[:300].split())}"
                for h in hits
            )
        if name == "read_section":
            section_id = args.get("section_id")
            if not isinstance(section_id, str):
                raise ToolError("read_section needs section_id (string)")
            section = self.store.section(section_id)
            if section is None:
                raise ToolError(f"Unknown section_id: {section_id}")
            return f"{' › '.join(section.heading_path)}\n\n{section.text}"
        raise ToolError(f"Unknown tool: {name}")

    def lookup(self, section_id: str) -> Citation | None:
        section = self.store.section(section_id)
        if section is None:
            return None
        title = self._titles.get(section.manual_id, section.manual_id)
        return Citation(section.manual_id, title, section.id, section.heading_path, "")
