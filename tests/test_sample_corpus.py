from pathlib import Path

from uma.corpus.ingest import ingest

SAMPLE = Path(__file__).resolve().parent.parent / "sample_manuals"


def test_sample_corpus_planted_cases(tmp_store, embedder):
    r = ingest(SAMPLE, tmp_store, embedder)
    assert r.manuals == 3 and not r.skipped
    sections = tmp_store.sections()
    text = {s.id: s.text for s in sections}

    # contradiction: factory reset hold time
    assert any("10 seconds" in t for k, t in text.items() if k.startswith("nimbus-thermostat:"))
    assert any("5 seconds" in t for k, t in text.items() if k.startswith("nimbus-app:"))

    # gap: no voice assistants or HomeKit anywhere
    banned = ("alexa", "homekit", "siri", "google assistant", "voice assistant")
    assert not any(w in t.lower() for t in text.values() for w in banned)

    # duplicate heading and stable ids later tasks rely on
    assert "nimbus-hub:hub-guide:pairing-devices" in text
    assert "3 seconds" in text["nimbus-hub:hub-guide:pairing-devices"]
    assert "nimbus-hub:hub-guide:reset" in text
    assert "nimbus-hub:hub-guide:reset-1" in text

    # overlap sections exist
    for sid in (
        "nimbus-thermostat:settings:connect-to-a-hub",
        "nimbus-thermostat:settings:factory-reset",
        "nimbus-app:pairing:add-a-thermostat",
        "nimbus-app:troubleshooting:reset-the-thermostat",
    ):
        assert sid in text, sid

    # error codes E1-E4 documented, E3 in its own section
    thermo = " ".join(" ".join(s.heading_path) + " " + s.text for s in sections if s.manual_id == "nimbus-thermostat")
    assert all(code in thermo for code in ("E1", "E2", "E3", "E4"))
    assert any(s.manual_id == "nimbus-thermostat" and s.anchor.startswith("e3") for s in sections)

    # html boilerplate stripped
    assert not any("©" in t for t in text.values())
    assert not any("Skip to content" in t for t in text.values())
