import inspect

from uma.config import load_settings
from uma.llm import FakeLLM, LLMError, LLMResponse, Usage, text_response
from uma.strategies import baseline
from uma.strategies.base import TRUNCATED, Failed, Final, TextDelta
from uma.strategies.baseline import BaselineStrategy
from uma.strategies.rules import ANSWERING_RULES, BASELINE_RULES


async def _run(llm, q="How do I pair the hub?"):
    return [e async for e in BaselineStrategy(llm, load_settings({})).answer(q)]


def test_identity():
    s = BaselineStrategy(FakeLLM([]), load_settings({}))
    assert s.id == "baseline" and s.title == "No retrieval"


async def test_request_is_the_question_only():
    llm = FakeLLM([text_response("x\n<status>answered</status>")])
    await _run(llm, "What is Wi-Fi?")
    call = llm.calls[0]
    assert call["system"] == BASELINE_RULES
    assert call["messages"] == [{"role": "user", "content": "What is Wi-Fi?"}]
    assert call["tools"] is None


def test_baseline_rules_do_not_restrict_to_manuals():
    assert "ONLY from the manual content" not in BASELINE_RULES
    assert "manual content provided" not in BASELINE_RULES
    for tag in ("<status>answered</status>", "<status>not_covered</status>",
                "<status>contradiction_found</status>"):
        assert tag in BASELINE_RULES and tag in ANSWERING_RULES
    assert "training cutoff" in BASELINE_RULES


async def test_streams_text_and_parses_answered_status():
    llm = FakeLLM([text_response("Wi-Fi is wireless networking.\n<status>answered</status>")])
    events = await _run(llm)
    deltas = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert deltas.strip() == "Wi-Fi is wireless networking."
    assert "<status>" not in deltas
    final = events[-1]
    assert isinstance(final, Final)
    assert final.answer.status == "answered"
    assert final.answer.text.strip() == "Wi-Fi is wireless networking."
    assert final.answer.citations == [] and final.answer.metrics.manuals_used == []
    assert final.answer.metrics.cost_usd is not None and final.answer.metrics.latency_ms >= 0


async def test_not_covered_status():
    llm = FakeLLM([text_response("I don't know; my information may be out of date.\n"
                                 "<status>not_covered</status>")])
    events = await _run(llm)
    assert events[-1].answer.status == "not_covered"


async def test_citations_in_response_are_ignored():
    cit = {"type": "char_location", "document_index": 0, "cited_text": "x"}
    llm = FakeLLM([text_response("Hi.", citations=[cit])])
    events = await _run(llm)
    assert events[-1].answer.citations == [] and events[-1].answer.text == "Hi."


async def test_refusal_becomes_failed():
    llm = FakeLLM([LLMResponse([], "refusal", Usage(1, 0))])
    assert (await _run(llm))[-1] == Failed("The model declined this question")


async def test_max_tokens_becomes_failed():
    llm = FakeLLM([LLMResponse([{"type": "text", "text": "cut"}], "max_tokens", Usage(1, 1))])
    assert (await _run(llm))[-1] == Failed(TRUNCATED)


async def test_llm_error_becomes_failed():
    class Boom(FakeLLM):
        async def stream(self, **kw):
            raise LLMError("ANTHROPIC_API_KEY is not set.")
            yield  # pragma: no cover

    assert (await _run(Boom([])))[-1] == Failed("ANTHROPIC_API_KEY is not set.")


async def test_never_touches_store_or_search():
    # The constructor takes no store or embedder, and the module imports neither.
    params = list(inspect.signature(BaselineStrategy).parameters)
    assert params == ["llm", "settings"]
    src = inspect.getsource(baseline)
    for name in ("CorpusStore", "uma.corpus", "uma.search", "Embedder", "count_tokens"):
        assert name not in src, name
    llm = FakeLLM([text_response("x")])
    await _run(llm)
    assert len(llm.calls) == 1
