"""Docs stay in step with the diagram sources the app serves."""

from pathlib import Path

from fastapi.testclient import TestClient

from uma.config import Settings
from uma.llm import FakeLLM
from uma.web import create_app

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "uma" / "static"


def test_overview_embeds_diagram():
    src = (STATIC / "diagrams" / "overview.mmd").read_text().strip()
    text = (ROOT / "docs" / "architecture" / "overview.md").read_text()
    assert f"```mermaid\n{src}\n```" in text


def test_overview_diagram_shows_baseline():
    src = (STATIC / "diagrams" / "overview.mmd").read_text()
    assert 'S0["No retrieval"]' in src and "S0 & S1 & S2 & S3" in src


def test_overview_diagram_shows_agentic_web():
    src = (STATIC / "diagrams" / "overview.mmd").read_text()
    assert 'S4["Agentic & web"]' in src and "S0 & S1 & S2 & S3 & S4" in src


def test_every_api_diagram_exists(tmp_path):
    settings = Settings(db_path=tmp_path / "uma.db")
    client = TestClient(create_app(settings, llm=FakeLLM([]), embedder=object()))
    strategies = client.get("/api/strategies").json()
    assert len(strategies) == 5
    for s in strategies:
        for kind in ("flow", "sequence"):
            path = STATIC / s[kind].removeprefix("/static/")
            assert s[kind].startswith("/static/diagrams/")
            assert path.is_file(), f"{s[kind]} has no file"
            assert path.read_text().strip()


def test_overview_links_every_adr():
    text = (ROOT / "docs" / "architecture" / "overview.md").read_text()
    for adr in (ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"):
        assert f"../adr/{adr.name}" in text, f"overview does not link {adr.name}"


STRATEGY_DOCS = [
    ("baseline", "0-baseline.md"),
    ("whole_context", "1-whole-context.md"),
    ("rag", "2-rag.md"),
    ("agentic", "3-agentic.md"),
    ("agentic_web", "4-agentic-web.md"),
]

EXPLAINER_HEADINGS = [
    "## In one paragraph",
    "## Diagrams",
    "## Step by step",
    "## Prefer when",
    "## Avoid when",
    "## Cost and latency",
    "## Typical failure modes",
    "## What to look for in the demo",
]


def test_strategy_docs_embed_current_diagrams():
    for sid, doc in STRATEGY_DOCS:
        text = (ROOT / "docs" / "strategies" / doc).read_text()
        for kind in ("flow", "sequence"):
            src = (STATIC / "diagrams" / f"{sid}-{kind}.mmd").read_text().strip()
            assert f"```mermaid\n{src}\n```" in text, f"{doc} does not embed {sid}-{kind}.mmd"


def test_strategy_docs_use_the_fixed_headings_in_order():
    # Stable anchors: the app links to #avoid-when when the corpus is too large.
    for _, doc in STRATEGY_DOCS:
        lines = (ROOT / "docs" / "strategies" / doc).read_text().splitlines()
        h2 = [line.rstrip() for line in lines if line.startswith("## ")]
        assert h2 == EXPLAINER_HEADINGS, doc
