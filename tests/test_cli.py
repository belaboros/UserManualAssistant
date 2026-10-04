import uma.__main__ as cli
from uma.embedding import HashingEmbedder


def test_ingest_sample_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("UMA_DB_PATH", str(tmp_path / "uma.db"))
    monkeypatch.setattr(cli, "make_embedder", lambda: HashingEmbedder())
    assert cli.main(["ingest", "--sample"]) == 0
    assert "3 manuals" in capsys.readouterr().out


def test_ingest_missing_dir_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("UMA_DB_PATH", str(tmp_path / "uma.db"))
    monkeypatch.setattr(cli, "make_embedder", lambda: HashingEmbedder())
    assert cli.main(["ingest", "--manuals-dir", str(tmp_path / "nope")]) == 1
    assert "not found" in capsys.readouterr().err
