import pytest

from uma.corpus.store import CorpusStore
from uma.embedding import HashingEmbedder


@pytest.fixture
def tmp_store(tmp_path):
    return CorpusStore(tmp_path / "db" / "uma.db")


@pytest.fixture
def embedder():
    return HashingEmbedder()


@pytest.fixture
def mini_corpus(tmp_path):
    root = tmp_path / "manuals"
    a = root / "alpha"
    a.mkdir(parents=True)
    (a / "manual.yaml").write_text("title: Alpha Router\nowner: Support\n")
    (a / "guide.md").write_text("# Setup\nPlug in the router.\n## Reset\nHold the button 10 s.\n")
    b = root / "beta"
    b.mkdir()
    (b / "manual.yaml").write_text("id: beta\ntitle: Beta Camera\nowner: Support\nvisibility: external\n")
    (b / "index.html").write_text(
        "<html><body><h1>Install</h1><p>Mount the camera.</p>"
        "<h2>Pairing</h2><p>Open the app and scan the code.</p></body></html>"
    )
    return root
