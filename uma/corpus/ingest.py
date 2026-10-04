"""Ingest manual folders (manual.yaml + md/html files) into the corpus store."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from uma.corpus.chunking import chunk_sections
from uma.corpus.models import ManualMeta, Section
from uma.corpus.parse_html import parse_html
from uma.corpus.parse_markdown import parse_markdown
from uma.corpus.store import CorpusStore
from uma.embedding import Embedder

MARKDOWN_SUFFIXES = {".md", ".markdown"}
HTML_SUFFIXES = {".html", ".htm"}


@dataclass
class IngestReport:
    manuals: int
    sections: int
    chunks: int
    skipped: list[str] = field(default_factory=list)


def load_manual_meta(folder: Path) -> ManualMeta:
    path = folder / "manual.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data.get("title"):
        raise ValueError(f"{path}: missing required field 'title'")
    return ManualMeta(
        id=str(data.get("id") or folder.name),
        title=str(data["title"]),
        owner=str(data.get("owner") or ""),
        visibility=data.get("visibility") or "internal",
        base_url=data.get("base_url"),
    )


def parse_manual(folder: Path, meta: ManualMeta) -> list[Section]:
    suffixes = MARKDOWN_SUFFIXES | HTML_SUFFIXES
    files = sorted(
        (p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in suffixes),
        key=lambda p: p.relative_to(folder).as_posix(),
    )
    sections: list[Section] = []
    for p in files:
        parse = parse_markdown if p.suffix.lower() in MARKDOWN_SUFFIXES else parse_html
        sections += parse(
            p.read_text(encoding="utf-8"),
            manual_id=meta.id,
            doc_path=p.relative_to(folder).as_posix(),
            base_url=meta.base_url,
            start_position=len(sections),
        )
    return sections


def ingest(manuals_dir: Path, store: CorpusStore, embedder: Embedder) -> IngestReport:
    store.reset()
    report = IngestReport(0, 0, 0)
    for folder in sorted(p for p in manuals_dir.iterdir() if p.is_dir()):
        if not (folder / "manual.yaml").exists():
            report.skipped.append(folder.name)
            continue
        meta = load_manual_meta(folder)
        sections = parse_manual(folder, meta)
        chunks = chunk_sections(sections)
        store.add_manual(meta)
        store.add_sections(sections)
        if chunks:
            store.add_chunks(chunks, embedder.embed([c.text for c in chunks]))
        report.manuals += 1
        report.sections += len(sections)
        report.chunks += len(chunks)
    return report
