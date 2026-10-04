import pytest

from uma.strategies.manual_tools import ManualTools, ToolError

PAIRING = "nimbus-hub:hub-guide:pairing-devices"


def test_run_and_lookup(sample_store, embedder):
    tools = ManualTools(sample_store, embedder)
    assert tools.run("read_section", {"section_id": PAIRING}).endswith(sample_store.section(PAIRING).text)
    with pytest.raises(ToolError):
        tools.run("nope", {})
    assert tools.lookup(PAIRING).section_id == PAIRING
    assert tools.lookup("missing") is None
