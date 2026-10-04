from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ManualMeta:
    id: str
    title: str
    owner: str
    visibility: Literal["internal", "external"]
    base_url: str | None


@dataclass(frozen=True)
class Section:
    id: str
    manual_id: str
    doc_path: str
    heading_path: tuple[str, ...]
    anchor: str
    text: str
    position: int
    source_url: str | None


@dataclass(frozen=True)
class Chunk:
    id: str
    section_id: str
    manual_id: str
    text: str
    position: int


@dataclass
class ManualRecord:
    meta: ManualMeta
    section_count: int
    token_count: int | None
