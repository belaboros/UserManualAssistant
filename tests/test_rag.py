import json

from uma.config import load_settings
from uma.llm import FakeLLM, text_response
from uma.search import hybrid_search
from uma.strategies.base import Final, TraceStep
from uma.strategies.rag import RagStrategy
from uma.strategies.rules import ANSWERING_RULES

Q = "How do I pair the thermostat with the hub?"


def _cit(index):
    return {"type": "content_block_location", "document_index": index, "start_block_index": 0,
            "end_block_index": 1, "cited_text": "x"}


async def _run(store, embedder, llm, settings=None, q=Q):
    strat = RagStrategy(store, embedder, llm, settings or load_settings({}))
    return [e async for e in strat.answer(q)]


async def test_retrieval_trace_then_answer(sample_store, embedder):
    llm = FakeLLM([text_response("Answer [cited].\n<status>answered</status>", citations=[_cit(0)])])
    events = await _run(sample_store, embedder, llm)
    assert isinstance(events[0], TraceStep) and events[0].kind == "retrieved"
    sent_docs = [b for b in llm.calls[0]["messages"][0]["content"] if b["type"] == "document"]
    assert len(sent_docs) == len(events[0].detail["chunks"]) and len(sent_docs) >= 8
    assert events[-1].answer.citations[0].section_id == events[0].detail["chunks"][0]["section_id"]
    assert events[-1].answer.citations[0].manual_title == events[0].detail["chunks"][0]["manual_title"]


async def test_documents_shape_and_no_cache_breakpoint(sample_store, embedder):
    llm = FakeLLM([text_response("x")])
    events = await _run(sample_store, embedder, llm)
    content = llm.calls[0]["messages"][0]["content"]
    docs, question = content[:-1], content[-1]
    assert question == {"type": "text", "text": Q}
    first = events[0].detail["chunks"][0]
    assert docs[0]["title"] == f"{first['manual_title']} — {' › '.join(first['heading_path'])}"
    assert docs[0]["citations"] == {"enabled": True}
    assert docs[0]["source"]["type"] == "content"
    assert docs[0]["source"]["content"][0]["type"] == "text"
    assert all("cache_control" not in d for d in docs)
    assert not any("cache_control" in b for b in content)


async def test_trace_is_json_safe(sample_store, embedder):
    events = await _run(sample_store, embedder, FakeLLM([text_response("x")]))
    detail = events[0].detail
    json.dumps(detail)
    for c in detail["chunks"]:
        assert type(c["score"]) is float and isinstance(c["heading_path"], list)


async def test_rag_uses_settings_top_k(sample_store, embedder):
    llm = FakeLLM([text_response("x")])
    events = await _run(sample_store, embedder, llm, load_settings({"RAG_TOP_K": "3"}))
    sent = [b for b in llm.calls[0]["messages"][0]["content"] if b["type"] == "document"]
    chunks = events[0].detail["chunks"]
    assert len(sent) >= 3 and len(sent) == len(chunks)
    top3 = hybrid_search(sample_store, embedder, Q, k=10_000)[:3]
    assert [c["section_id"] for c in chunks[:3]] == [h.section.id for h in top3]
    assert len(sent) < 8  # fewer than the default top_k


async def test_rag_uses_shared_rules(sample_store, embedder):
    llm = FakeLLM([text_response("x")])
    await _run(sample_store, embedder, llm)
    assert llm.calls[0]["system"].startswith(ANSWERING_RULES)


async def test_out_of_range_citation_dropped(sample_store, embedder):
    llm = FakeLLM([text_response("Hi.", citations=[_cit(99), {"type": "char_location"}])])
    events = await _run(sample_store, embedder, llm)
    assert isinstance(events[-1], Final) and events[-1].answer.citations == []


async def test_retrieval_runs_off_the_event_loop_thread(sample_store, embedder, monkeypatch):
    import threading

    import uma.strategies.rag as rag_mod

    threads = []
    original = rag_mod.retrieve_for_rag

    def spy(*args, **kwargs):
        threads.append(threading.current_thread())
        return original(*args, **kwargs)

    monkeypatch.setattr(rag_mod, "retrieve_for_rag", spy)
    llm = FakeLLM([text_response("ok\n<status>answered</status>")])
    events = [e async for e in RagStrategy(sample_store, embedder, llm, load_settings({})).answer("pair?")]
    assert events[-1].answer.status == "answered"
    assert len(threads) == 1 and threads[0] is not threading.main_thread()
