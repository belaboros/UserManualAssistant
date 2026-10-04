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


def test_every_api_diagram_exists(tmp_path):
    settings = Settings(db_path=tmp_path / "uma.db")
    client = TestClient(create_app(settings, llm=FakeLLM([]), embedder=object()))
    strategies = client.get("/api/strategies").json()
    assert len(strategies) == 3
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
