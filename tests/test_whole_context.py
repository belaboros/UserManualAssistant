from uma.config import load_settings
from uma.llm import FakeLLM, LLMError, LLMResponse, Usage, text_response
from uma.strategies.base import Failed, Final, TextDelta
from uma.strategies.whole_context import CORPUS_TOO_LARGE_DOC, WholeContextStrategy


async def _run(store, llm, q="pair?"):
    return [e async for e in WholeContextStrategy(store, llm, load_settings({})).answer(q)]


async def test_streams_text_and_final_with_citations(sample_store):
    cit = {"type": "content_block_location", "document_index": 1, "start_block_index": 0,
           "end_block_index": 1, "cited_text": "Hold the Link button"}
    llm = FakeLLM([text_response("Hold Link 3 s.", citations=[cit])], token_count=40_000)
    llm.responses[0].content.append({"type": "text", "text": "\n<status>answered</status>"})
    events = await _run(sample_store, llm)
    final = events[-1].answer
    assert final.status == "answered" and final.text.strip() == "Hold Link 3 s. [1]"
    assert final.citations[0].manual_id == "nimbus-hub"
    assert final.citations[0].cited_text == "Hold the Link button"
    assert final.metrics.manuals_used == [final.citations[0].manual_title]
    assert final.metrics.cost_usd is not None and final.metrics.latency_ms >= 0
    assert "<status>" not in "".join(e.text for e in events if isinstance(e, TextDelta))


async def test_request_contains_every_section_and_cache_breakpoint(sample_store):
    llm = FakeLLM([text_response("x")], token_count=40_000)
    await _run(sample_store, llm)
    content = llm.calls[0]["messages"][0]["content"]
    docs, question = content[:-1], content[-1]
    assert len(docs) == 3 and question == {"type": "text", "text": "pair?"}
    assert sum(len(d["source"]["content"]) for d in docs) == len(sample_store.sections())
    assert [("cache_control" in d) for d in docs] == [False, False, True]
    assert all(d["citations"] == {"enabled": True} and d["source"]["type"] == "content" for d in docs)


async def test_too_large_corpus_fails_with_hint(sample_store):
    events = await _run(sample_store, FakeLLM([], token_count=900_000), "q")
    assert isinstance(events[-1], Failed) and "900,000" in events[-1].message
    assert events[-1].hint_doc == CORPUS_TOO_LARGE_DOC


async def test_token_count_cached_in_store(sample_store):
    llm = FakeLLM([text_response("a"), text_response("b")], token_count=40_000)
    calls = 0
    orig = llm.count_tokens

    async def counting(**kw):
        nonlocal calls
        calls += 1
        return await orig(**kw)

    llm.count_tokens = counting
    await _run(sample_store, llm)
    await _run(sample_store, llm)
    assert calls == 1 and sample_store.corpus_token_count() == 40_000


async def test_refusal_becomes_failed(sample_store):
    llm = FakeLLM([LLMResponse([], "refusal", Usage(1, 0))], token_count=40_000)
    events = await _run(sample_store, llm)
    assert events[-1] == Failed("The model declined this question")


async def test_empty_content_does_not_crash(sample_store):
    llm = FakeLLM([LLMResponse([], "end_turn", Usage(1, 0))], token_count=40_000)
    events = await _run(sample_store, llm)
    assert isinstance(events[-1], Final) and events[-1].answer.text == ""


async def test_llm_error_becomes_failed(sample_store):
    class Boom(FakeLLM):
        async def stream(self, **kw):
            raise LLMError("ANTHROPIC_API_KEY is not set.")
            yield  # pragma: no cover

    events = await _run(sample_store, Boom([], token_count=40_000))
    assert events[-1] == Failed("ANTHROPIC_API_KEY is not set.")


async def test_unresolvable_citation_is_dropped(sample_store):
    bad = {"type": "char_location", "document_index": 0}
    oob = {"type": "content_block_location", "document_index": 9, "start_block_index": 0,
           "end_block_index": 1, "cited_text": "x"}
    llm = FakeLLM([text_response("Hi.", citations=[bad, oob])], token_count=40_000)
    events = await _run(sample_store, llm)
    assert events[-1].answer.citations == [] and events[-1].answer.text == "Hi."


async def test_whole_context_uses_shared_rules(sample_store):
    from uma.strategies.rules import ANSWERING_RULES

    llm = FakeLLM([text_response("x")], token_count=40_000)
    await _run(sample_store, llm)
    assert llm.calls[0]["system"].startswith(ANSWERING_RULES)


async def test_trailing_partial_tag_is_flushed_as_text(sample_store):
    llm = FakeLLM([text_response("Answer <sta")], token_count=40_000)
    events = await _run(sample_store, llm)
    deltas = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert deltas == "Answer <sta" == events[-1].answer.text
