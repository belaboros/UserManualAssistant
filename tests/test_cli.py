import uma.__main__ as cli
from uma.embedding import HashingEmbedder


def test_ingest_sample_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("UMA_DB_PATH", str(tmp_path / "uma.db"))
    monkeypatch.setattr(cli, "make_embedder", lambda: HashingEmbedder())
    assert cli.main(["ingest", "--sample"]) == 0
    assert "3 manuals" in capsys.readouterr().out


def test_ingest_missing_dir_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("UMA_DB_PATH", str(tmp_path / "uma.db"))
    monkeypatch.setattr(cli, "make_embedder", lambda: HashingEmbedder())
    assert cli.main(["ingest", "--manuals-dir", str(tmp_path / "nope")]) == 1
    assert "not found" in capsys.readouterr().err


def test_sample_and_manuals_dir_are_exclusive(monkeypatch):
    import pytest
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli.main(["ingest", "--sample", "--manuals-dir", "x"])



def test_serve_warms_up_embedder_before_uvicorn(tmp_path, monkeypatch, capsys):
    import uvicorn

    order = []

    class RecordingEmbedder(HashingEmbedder):
        def embed(self, texts):
            order.append(("embed", list(texts)))
            return super().embed(texts)

    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("UMA_DB_PATH", str(tmp_path / "uma.db"))
    monkeypatch.setattr(cli, "make_embedder", lambda: RecordingEmbedder())
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: order.append(("run", kw)))
    assert cli.main(["serve", "--port", "8123"]) == 0
    assert [o[0] for o in order] == ["embed", "run"]
    assert order[1][1]["port"] == 8123
    assert "Loading embedding model" in capsys.readouterr().out
