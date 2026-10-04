import subprocess
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from uma.config import load_settings
from uma.llm import (
    AnthropicLLM,
    Completed,
    FakeLLM,
    LLMError,
    LLMResponse,
    TextChunk,
    Usage,
    credentials_available,
    text_response,
)


class _Block:
    def __init__(self, data):
        self._data = data

    def model_dump(self, exclude_none=False):
        return {k: v for k, v in self._data.items() if not (exclude_none and v is None)}


def fake_sdk_message():
    return SimpleNamespace(
        content=[_Block({"type": "text", "text": "Hi there", "citations": None})],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=11, output_tokens=7, cache_read_input_tokens=3, cache_creation_input_tokens=2
        ),
    )


class _Stream:
    def __init__(self, final_message, error=None):
        self._final = final_message
        self._error = error

    @property
    def text_stream(self):
        async def gen():
            if self._error:
                raise self._error
            yield "Hi "
            yield "there"

        return gen()

    async def get_final_message(self):
        return self._final


class _StreamCM:
    def __init__(self, stream):
        self._stream = stream

    async def __aenter__(self):
        return self._stream

    async def __aexit__(self, *exc):
        return False


class RecordingClient:
    """Test double for anthropic.AsyncAnthropic: records the kwargs it was called with."""

    def __init__(self, final_message=None, error=None, input_tokens=42):
        self.last_kwargs = None
        self.count_kwargs = None
        self._final = final_message
        self._error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

        async def count_tokens(**kw):
            self.count_kwargs = kw
            return SimpleNamespace(input_tokens=input_tokens)

        self.messages = SimpleNamespace(count_tokens=count_tokens)

    def _stream(self, **kwargs):
        self.last_kwargs = kwargs
        return _StreamCM(_Stream(self._final, self._error))


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr("uma.llm.credentials_available", lambda: True)


async def test_fake_llm_streams_then_completes():
    llm = FakeLLM([text_response("Hello world")])
    events = [e async for e in llm.stream(system="s", messages=[])]
    assert "".join(e.text for e in events if isinstance(e, TextChunk)) == "Hello world"
    assert sum(isinstance(e, TextChunk) for e in events) == 2
    assert isinstance(events[-1], Completed) and llm.calls[0]["system"] == "s"


async def test_fake_llm_does_not_mutate_script_and_runs_out():
    scripted = text_response("abc", citations=[{"n": 1}])
    llm = FakeLLM([scripted])
    events = [e async for e in llm.stream(system="s", messages=[], tools=None)]
    done = events[-1].response
    assert done == scripted and done is not scripted
    done.content[0]["text"] = "changed"
    assert llm.responses[0].content[0]["text"] == "abc"
    with pytest.raises(AssertionError):
        _ = [e async for e in llm.stream(system="s", messages=[])]


async def test_fake_llm_count_tokens():
    llm = FakeLLM([], token_count=123)
    assert await llm.count_tokens(system="s", messages=[]) == 123


def test_text_response_shape():
    r = text_response("x", citations=[{"a": 1}])
    assert isinstance(r, LLMResponse) and r.stop_reason == "end_turn"
    assert r.content == [{"type": "text", "text": "x", "citations": [{"a": 1}]}]
    assert text_response("x").content == [{"type": "text", "text": "x"}]


async def test_anthropic_llm_request_shape(creds):
    client = RecordingClient(final_message=fake_sdk_message())
    llm = AnthropicLLM(load_settings({}), client=client)
    events = [e async for e in llm.stream(system="s", messages=[{"role": "user", "content": "q"}])]
    kw = client.last_kwargs
    assert kw["model"] == "claude-sonnet-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "medium"} and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["extra_body"] == {"fallbacks": "default"} and "tool_choice" not in kw
    assert kw["cache_control"] == {"type": "ephemeral"} and kw["max_tokens"] == 16000
    assert "tools" not in kw
    assert "".join(e.text for e in events if isinstance(e, TextChunk)) == "Hi there"
    resp = events[-1].response
    assert resp.content == [{"type": "text", "text": "Hi there"}] and resp.stop_reason == "end_turn"
    assert resp.usage == Usage(11, 7, 3, 2)


async def test_anthropic_llm_passes_tools(creds):
    client = RecordingClient(final_message=fake_sdk_message())
    tools = [{"name": "t"}]
    llm = AnthropicLLM(load_settings({}), client=client)
    _ = [e async for e in llm.stream(system="s", messages=[], tools=tools)]
    assert client.last_kwargs["tools"] == tools


async def test_anthropic_llm_count_tokens(creds):
    client = RecordingClient(input_tokens=77)
    n = await AnthropicLLM(load_settings({}), client=client).count_tokens(system="s", messages=[])
    assert n == 77 and client.count_kwargs["model"] == "claude-sonnet-5-5"


async def test_missing_credentials_raises_llm_error(monkeypatch):
    monkeypatch.setattr("uma.llm.credentials_available", lambda: False)
    llm = AnthropicLLM(load_settings({}))
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        _ = [e async for e in llm.stream(system="s", messages=[])]
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        await llm.count_tokens(system="s", messages=[])


async def test_rate_limit_maps_to_llm_error(creds):
    resp = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    err = anthropic.RateLimitError("slow down", response=resp, body=None)
    client = RecordingClient(error=err)
    with pytest.raises(LLMError, match="rate limit"):
        _ = [e async for e in AnthropicLLM(load_settings({}), client=client).stream(system="s", messages=[])]


def test_credentials_available_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert credentials_available() is True


def test_credentials_available_ant_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    assert credentials_available() is False
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert credentials_available() is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    assert credentials_available() is False
