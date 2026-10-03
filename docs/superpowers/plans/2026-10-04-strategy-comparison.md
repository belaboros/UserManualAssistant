# Retrieval Strategy Comparison v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web app that answers one question with three retrieval strategies side by side (whole-context, RAG, agentic), lets the user rate each answer 1–5 stars, shows a leaderboard, and documents each strategy well enough to teach it.

**Architecture:** A Python package `uma`.
- An ingestion step parses HTML and Markdown manuals into sections and chunks, stored in SQLite with FTS5 and local embeddings.
- Three strategy classes implement one `Strategy` protocol and share one LLM wrapper, one set of answering rules and one hybrid search.
- A runner streams all three in parallel over SSE to a vanilla-JS page.
- Votes and answers are logged in the same SQLite file.

**Tech Stack:** Python 3.12, uv, FastAPI, Uvicorn, `anthropic` (async), markdown-it-py, selectolax, PyYAML, numpy, fastembed (`BAAI/bge-small-en-v1.5`), python-dotenv, pytest, pytest-asyncio, httpx; frontend: plain HTML/CSS/JS with mermaid.js, marked, DOMPurify from a CDN.

**Spec:** [`docs/superpowers/specs/2026-10-04-strategy-comparison-design.md`](../specs/2026-10-04-strategy-comparison-design.md). Decisions: [`docs/adr/`](../../adr/README.md). ADR 0011 supersedes 0007.

## Global Constraints

- Python `>=3.12`, dependencies declared in `pyproject.toml` and locked with uv. Use only the libraries listed under Tech Stack. Any new library or technology needs a new ADR in `docs/adr/`, added to the ADR index.
- Model defaults:
  - `UMA_MODEL=claude-sonnet-5-5` and `UMA_EFFORT=medium`;
  - `thinking={"type": "adaptive"}`, never disabled;
  - no forced `tool_choice`; no assistant prefill.
- Server-side refusal fallback on every Claude call: beta `server-side-fallback-2026-07-01` with `fallbacks: "default"`, passed through `extra_body`.
- All three strategies use the same model, the same effort and the same `ANSWERING_RULES` text (ADR 0006). A strategy may append only a description of its own mechanism.
- Defaults:
  - `WHOLE_CONTEXT_MAX_TOKENS=800000`, `RAG_TOP_K=8`, `AGENT_MAX_TOOL_CALLS=8`, `STRATEGY_TIMEOUT_S=90`;
  - chunk size 400 tokens, where 1 token ≈ 4 characters;
  - hybrid search: 30 candidates per method, RRF constant 60;
  - coverage ratio 0.5.
- Database: `data/uma.db`. `manuals/`, `data/` and `.env` are git-ignored. Real manuals are never committed.
- No frontend build step and no npm.
- Tests never call the real API or download models. The only exception is `pytest -m live`, which is opt-in and skipped by default.
- Status tags: exactly `<status>answered</status>`, `<status>not_covered</status>`, `<status>contradiction_found</status>`.
- Citation markers in the final answer text are `[n]`, with 1-based indexes into `Answer.citations`.

## Review Focus

1. **A manual file with no headings, or with text before its first heading.** That text becomes a section, never silently dropped. Owned by Task 2 (`test_text_without_headings_becomes_intro_section`) and Task 3 (`test_html_without_headings`).
2. **Duplicate headings in one document**, such as two "Reset" sections. Each must get a unique anchor and section ID; otherwise inserting into SQLite fails or citations point to the wrong section. Owned by Task 2 (`test_duplicate_headings_get_unique_anchors`).
3. **Questions containing FTS5 syntax characters**: `"`, `*`, `:`, `(`, `-`, `C++`, `AND`. The search must not raise and must still return matches. Owned by Task 5 (`test_fts_search_tolerates_special_characters`).
4. **A status tag split across stream chunks, or a literal `<` in the answer text** such as "temperature < 5 °C". The tag must be hidden, the status detected, and ordinary `<` text passed through untouched. Owned by Task 7 (`test_tag_split_across_chunks`, `test_literal_angle_bracket_passes_through`).
5. **Votes with invalid stars (0, 6), on failed answers, or repeated on the same answer.** Invalid stars and failed answers are rejected with HTTP 400; a repeated vote replaces the earlier one. Owned by Task 12 (`test_vote_rejects_out_of_range`, `test_vote_on_failed_answer_rejected`, `test_vote_upsert_replaces`) and Task 14 (`test_post_vote_invalid_returns_400`).

---

## File Structure

```
pyproject.toml, .gitignore, .env.example, README.md
uma/
  __init__.py
  __main__.py              # CLI: ingest, serve                                   (Task 14)
  config.py                # Settings, prices, cost_usd                            (Task 1)
  embedding.py             # Embedder protocol, FastEmbedEmbedder, HashingEmbedder (Task 4)
  corpus/
    models.py              # ManualMeta, Section, Chunk, ManualRecord              (Task 2)
    slug.py                # slugify, unique anchors                               (Task 2)
    parse_markdown.py      # (Task 2)
    parse_html.py          # (Task 3)
    chunking.py            # (Task 4)
    store.py               # CorpusStore (SQLite corpus tables)                    (Task 4)
    ingest.py              # load_manual_meta, parse_manual, ingest                (Task 4)
  search.py                # hybrid_search, retrieve_for_rag                       (Task 5)
  llm.py                   # Usage, LLMResponse, LLM protocol, AnthropicLLM, FakeLLM (Task 8)
  strategies/
    base.py                # events, Answer, Citation, StatusTagFilter, helpers    (Task 7)
    rules.py               # ANSWERING_RULES                                       (Task 7)
    whole_context.py       # (Task 9)
    rag.py                 # (Task 10)
    agentic.py             # (Task 11)
  log.py                   # Log: questions, answers, votes                        (Task 12)
  runner.py                # run_question                                          (Task 12)
  leaderboard.py           # (Task 13)
  web.py                   # create_app                                            (Task 14)
  static/                  # index.html, app.js, leaderboard.html, leaderboard.js, style.css (Tasks 15–16)
  static/diagrams/*.mmd    # (Task 17)
sample_manuals/            # (Task 6)
docs/architecture/overview.md, docs/strategies/*.md, docs/choosing-a-strategy.md, docs/demo-questions.md (Tasks 17–18)
tests/                     # one test module per unit
```

---

### Task 1: Project scaffold, settings and cost calculation

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `uma/__init__.py`, `uma/config.py`, `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Settings` (frozen dataclass): `model: str = "claude-sonnet-5-5"`, `effort: str = "medium"`, `db_path: Path = Path("data/uma.db")`, `manuals_dir: Path = Path("manuals")`, `whole_context_max_tokens: int = 800_000`, `rag_top_k: int = 8`, `agent_max_tool_calls: int = 8`, `strategy_timeout_s: float = 90.0`.
  - `load_settings(env: Mapping[str, str] = os.environ) -> Settings`, reading `UMA_MODEL`, `UMA_EFFORT`, `UMA_DB_PATH`, `UMA_MANUALS_DIR`, `WHOLE_CONTEXT_MAX_TOKENS`, `RAG_TOP_K`, `AGENT_MAX_TOOL_CALLS`, `STRATEGY_TIMEOUT_S`.
  - `Price(input, output, cache_read, cache_write)`: USD per 1M tokens.
  - `PRICES: dict[str, Price]`.
  - `cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float | None`.

- [ ] **Step 1: Create `pyproject.toml` and `.gitignore`.**
  - `pyproject.toml`:
    - `[project]`, `requires-python = ">=3.12"`, runtime deps from Tech Stack;
    - dev group `pytest`, `pytest-asyncio`, `httpx`;
    - `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `markers = ["live: calls the real Claude API"]`, `addopts = "-m 'not live'"`.
  - `.gitignore`: `manuals/`, `data/`, `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`.
  - `.env.example` lists every variable from `load_settings`, plus `ANTHROPIC_API_KEY=`.
  - Run `uv sync`. Expected: it creates `.venv` and `uv.lock`.

- [ ] **Step 2: Write failing tests**

```python
def test_defaults():
    s = load_settings({})
    assert s.model == "claude-sonnet-5-5" and s.effort == "medium"
    assert s.whole_context_max_tokens == 800_000 and s.rag_top_k == 8
    assert s.agent_max_tool_calls == 8 and s.strategy_timeout_s == 90.0

def test_env_overrides():
    s = load_settings({"UMA_MODEL": "claude-opus-5-5", "RAG_TOP_K": "5", "UMA_DB_PATH": "/tmp/x.db"})
    assert s.model == "claude-opus-5-5" and s.rag_top_k == 5 and s.db_path == Path("/tmp/x.db")

def test_cost_sonnet():
    # 1M input @ $2, 100k output @ $10, 1M cache read @ $0.20, 100k cache write @ $2.50
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 100_000, 1_000_000, 100_000) == pytest.approx(2.0 + 1.0 + 0.2 + 0.25)

def test_cost_unknown_model_is_none():
    assert cost_usd("mystery-model", 10, 10) is None
```

- [ ] **Step 3: Run** `uv run pytest tests/test_config.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement `uma/config.py`.**
  - `PRICES`:
    - `"claude-sonnet-5-5": Price(2.00, 10.00, 0.20, 2.50)`;
    - `"claude-opus-5-5": Price(4.00, 20.00, 0.20, 5.00)`.
  - Add a comment that prices come from Anthropic's pricing as of 2026-09.
- [ ] **Step 5: Run** `uv run pytest -v`. Expected: 4 passed.
- [ ] **Step 6: Commit**: `git add -A && git commit -m "chore: scaffold uma package with settings and cost calculation"`

---

### Task 2: Corpus models and Markdown parser

**Files:**
- Create: `uma/corpus/__init__.py`, `uma/corpus/models.py`, `uma/corpus/slug.py`, `uma/corpus/parse_markdown.py`, `tests/test_parse_markdown.py`

**Interfaces:**
- Produces:
  - `ManualMeta(id: str, title: str, owner: str, visibility: Literal["internal","external"], base_url: str | None)`: frozen.
  - `Section(id: str, manual_id: str, doc_path: str, heading_path: tuple[str, ...], anchor: str, text: str, position: int, source_url: str | None)`: frozen.
    - `id = f"{manual_id}:{doc_stem}:{anchor or 'intro'}"`.
    - `source_url = f"{base_url.rstrip('/')}/{doc_path}#{anchor}"` when `base_url` is set, otherwise `None`.
    - `doc_path` is relative to the manual folder, using `/` separators.
  - `Chunk(id: str, section_id: str, manual_id: str, text: str, position: int)`: frozen.
  - `ManualRecord(meta: ManualMeta, section_count: int, token_count: int | None)`.
  - `slugify(heading: str) -> str`: GitHub style. Lowercase; drop characters that aren't alphanumeric, space or hyphen; spaces become `-`.
  - `UniqueAnchors()`, with `.make(heading: str) -> str`: the first occurrence gets the slug; repeats get `slug-1`, `slug-2`, and so on.
  - `parse_markdown(text: str, *, manual_id: str, doc_path: str, base_url: str | None, start_position: int = 0) -> list[Section]`.

- [ ] **Step 1: Write failing tests**

```python
MD = "# Setup\nIntro text.\n## Wi-Fi\nConnect it.\n## Reset\nHold 10 s.\n# Troubleshooting\n## Reset\nAgain.\n"

def test_heading_paths_and_text():
    s = parse_markdown(MD, manual_id="t2", doc_path="guide.md", base_url=None)
    assert [x.heading_path for x in s] == [("Setup",), ("Setup", "Wi-Fi"), ("Setup", "Reset"),
                                          ("Troubleshooting", "Reset")]
    assert s[1].text == "Connect it." and s[1].position == 1

def test_duplicate_headings_get_unique_anchors():
    s = parse_markdown(MD, manual_id="t2", doc_path="guide.md", base_url=None)
    assert [x.anchor for x in s] == ["setup", "wi-fi", "reset", "reset-1"]
    assert len({x.id for x in s}) == len(s)
    assert s[3].id == "t2:guide:reset-1"

def test_text_without_headings_becomes_intro_section():
    s = parse_markdown("Just a paragraph.\n\n# Later\nMore.", manual_id="m", doc_path="a.md", base_url=None)
    assert s[0].anchor == "" and s[0].id == "m:a:intro" and s[0].text == "Just a paragraph."

def test_heading_without_body_is_skipped_but_kept_in_path():
    s = parse_markdown("# A\n## B\nBody.", manual_id="m", doc_path="a.md", base_url=None)
    assert [x.heading_path for x in s] == [("A", "B")]

def test_source_url():
    s = parse_markdown("# Wi-Fi\nx", manual_id="m", doc_path="docs/net.md", base_url="https://ex.com/m/")
    assert s[0].source_url == "https://ex.com/m/docs/net.md#wi-fi"

def test_lists_and_code_kept_as_text():
    s = parse_markdown("# A\n- one\n- two\n\n```\ncode\n```", manual_id="m", doc_path="a.md", base_url=None)
    assert "one" in s[0].text and "code" in s[0].text
```

- [ ] **Step 2: Run** `uv run pytest tests/test_parse_markdown.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the parser.**
  - Use `markdown_it.MarkdownIt("commonmark")` tokens: `heading_open` marks heading boundaries.
  - Section text is the source lines between headings (take line ranges from `token.map`), stripped. Lists and code stay as Markdown source.
  - `heading_path` keeps a stack trimmed to the heading level.
- [ ] **Step 4: Run tests.** Expected: 6 passed.
- [ ] **Step 5: Commit**: `git commit -am "feat(corpus): section models and markdown parser"` (add the new files first).

---

### Task 3: HTML parser

**Files:**
- Create: `uma/corpus/parse_html.py`, `tests/test_parse_html.py`

**Interfaces:**
- Consumes: `Section`, `UniqueAnchors`, `slugify` (Task 2).
- Produces: `parse_html(html: str, *, manual_id: str, doc_path: str, base_url: str | None, start_position: int = 0) -> list[Section]`. Same semantics as `parse_markdown`.

- [ ] **Step 1: Write failing tests**

```python
PAGE = """<html><body><nav>Home | Docs</nav><header>Brand</header>
<main><h1 id="pairing">Pairing</h1><p>Open the app.</p><ul><li>Tap Add</li></ul>
<h2>Confirm</h2><p>Tap OK.</p><script>x()</script></main><footer>© 2026</footer></body></html>"""

def test_html_sections_and_boilerplate_removed():
    s = parse_html(PAGE, manual_id="app", doc_path="pair.html", base_url=None)
    assert [x.heading_path for x in s] == [("Pairing",), ("Pairing", "Confirm")]
    assert "Open the app." in s[0].text and "Tap Add" in s[0].text
    joined = " ".join(x.text for x in s)
    assert "Home | Docs" not in joined and "Brand" not in joined and "©" not in joined and "x()" not in joined

def test_existing_id_used_as_anchor():
    s = parse_html(PAGE, manual_id="app", doc_path="pair.html", base_url=None)
    assert s[0].anchor == "pairing" and s[1].anchor == "confirm"

def test_html_without_headings():
    s = parse_html("<body><p>Only text.</p></body>", manual_id="m", doc_path="a.html", base_url=None)
    assert len(s) == 1 and s[0].id == "m:a:intro" and s[0].text == "Only text."

def test_falls_back_to_body_without_main():
    s = parse_html("<body><h1>A</h1><p>b</p></body>", manual_id="m", doc_path="a.html", base_url=None)
    assert s[0].text == "b"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_parse_html.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement with selectolax `HTMLParser`.**
  - Decompose `nav, header, footer, aside, script, style, noscript`.
  - Content root: `main`, else `article`, else `body`.
  - Walk the root's descendants in document order. Each `h1`–`h6` starts a section. The text of the block elements `p, li, pre, td, th, dt, dd, blockquote` is appended as one line each.
  - Anchor: the heading's `id` attribute if it has one, otherwise `UniqueAnchors().make(heading text)`. Register `id` values with the same `UniqueAnchors` so duplicates still come out unique.
- [ ] **Step 4: Run tests.** Expected: 4 passed.
- [ ] **Step 5: Commit**: `feat(corpus): html parser with boilerplate stripping`.

---

### Task 4: Chunking, corpus store, embedder and ingestion

**Files:**
- Create: `uma/corpus/chunking.py`, `uma/corpus/store.py`, `uma/embedding.py`, `uma/corpus/ingest.py`, `tests/test_chunking.py`, `tests/test_store.py`, `tests/test_ingest.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: models and parsers (Tasks 2–3).
- Produces:
  - `chunk_sections(sections: list[Section], max_tokens: int = 400) -> list[Chunk]`.
    - One chunk per section. A section longer than `max_tokens*4` characters is split at blank-line paragraph boundaries; each split chunk after the first begins with the last paragraph of the previous chunk (overlap).
    - IDs are `f"{section.id}#{i}"`.
  - `Embedder` protocol: `dim: int` and `embed(texts: list[str]) -> np.ndarray`, returning an `(n, dim)` float32 array of L2-normalised rows.
  - `FastEmbedEmbedder(model_name: str = "BAAI/bge-small-en-v1.5")`: lazily loads `fastembed.TextEmbedding`.
  - `HashingEmbedder(dim: int = 256)`: deterministic. Lowercased word tokens are hashed into buckets with `hashlib.md5`, then normalised. Used by tests.
  - `CorpusStore(db_path: Path)`, with methods:
    - `reset() -> None`;
    - `add_manual(meta: ManualMeta) -> None`;
    - `add_sections(sections: list[Section]) -> None`;
    - `add_chunks(chunks: list[Chunk], embeddings: np.ndarray) -> None`;
    - `manuals() -> list[ManualRecord]`;
    - `sections(manual_id: str | None = None) -> list[Section]`, ordered by `(manual_id, position)`;
    - `section(section_id: str) -> Section | None`;
    - `chunk(chunk_id: str) -> Chunk`;
    - `chunk_matrix() -> tuple[list[str], np.ndarray]`;
    - `fts_search(query: str, limit: int, manual_id: str | None = None) -> list[tuple[str, float]]`, returning `(chunk_id, bm25)` with lower being better;
    - `set_token_count(manual_id: str | None, n: int) -> None`, where `None` means the whole corpus;
    - `corpus_token_count() -> int | None`;
    - `is_empty() -> bool`.
  - `load_manual_meta(folder: Path) -> ManualMeta`. Reads `manual.yaml`. `id` defaults to the folder name. `visibility` defaults to `"internal"`. A missing `title` raises `ValueError` that names the file.
  - `parse_manual(folder: Path, meta: ManualMeta) -> list[Section]`. Covers `*.md`, `*.markdown`, `*.html`, `*.htm`, recursively, sorted by relative path, with positions continuing across files.
  - `IngestReport(manuals: int, sections: int, chunks: int, skipped: list[str])`.
  - `ingest(manuals_dir: Path, store: CorpusStore, embedder: Embedder) -> IngestReport`. Resets the store first. A subfolder without `manual.yaml` goes into `skipped`.
  - `tests/conftest.py` fixtures:
    - `tmp_store` (a `CorpusStore` on `tmp_path`);
    - `embedder` (`HashingEmbedder()`);
    - `mini_corpus`: writes two tiny manuals (`alpha` in Markdown, `beta` in HTML) to `tmp_path` and returns the directory.

- [ ] **Step 1: Write failing tests**

```python
# test_chunking.py
def test_short_section_is_one_chunk(): ...  # 1 section, 100 chars -> 1 chunk, id "<section.id>#0"
def test_long_section_split_with_overlap():
    paras = [f"para{i} " + "x" * 600 for i in range(6)]
    sec = Section(id="m:a:s", manual_id="m", doc_path="a.md", heading_path=("S",), anchor="s",
                  text="\n\n".join(paras), position=0, source_url=None)
    chunks = chunk_sections([sec], max_tokens=400)   # 1600 chars max
    assert len(chunks) > 1 and all(c.section_id == "m:a:s" for c in chunks)
    assert chunks[1].text.startswith(chunks[0].text.split("\n\n")[-1])

# test_store.py
def test_roundtrip_and_fts(tmp_store, embedder): ...     # add manual/sections/chunks; sections() ordered; fts finds "router"
def test_fts_search_tolerates_special_characters(tmp_store, embedder):
    # store holds a chunk with text "Reset the C++ SDK: hold (button) 10 s"
    for q in ['"', "C++", "reset*", "hold: (button)", "AND", "-x", "what's up?"]:
        tmp_store.fts_search(q, limit=5)              # never raises
    assert tmp_store.fts_search("reset C++ sdk?", limit=5)[0][0] == chunk_id
def test_reset_clears(tmp_store, embedder): ...
def test_token_count_roundtrip(tmp_store): ...

# test_ingest.py
def test_ingest_mini_corpus(mini_corpus, tmp_store, embedder):
    r = ingest(mini_corpus, tmp_store, embedder)
    assert r.manuals == 2 and r.sections == len(tmp_store.sections()) and r.chunks >= r.sections
    assert {m.meta.id for m in tmp_store.manuals()} == {"alpha", "beta"}
def test_folder_without_yaml_skipped(mini_corpus, tmp_store, embedder): ...
def test_missing_title_raises(tmp_path): ...  # ValueError mentioning "manual.yaml"
def test_reingest_replaces(mini_corpus, tmp_store, embedder): ...  # run twice -> same counts
```

- [ ] **Step 2: Run** `uv run pytest tests/test_chunking.py tests/test_store.py tests/test_ingest.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **Store tables** match the spec §7: `manuals`, `sections`, `chunks`, and `chunks_fts` (a standalone FTS5 table with an unindexed `chunk_id` and `manual_id`). Add `corpus_meta(key, value)` for the corpus token count.
  - **Embeddings** are stored as `ndarray.astype(np.float32).tobytes()`.
  - **Connections:** open a new `sqlite3` connection per method, so the store is safe to call from async code.
  - **FTS sanitising:** extract `\w+` tokens, drop the FTS keywords (`AND`, `OR`, `NOT`, `NEAR`), quote each token, join with ` OR `, and return `[]` when no tokens remain. Order by `bm25(chunks_fts)`.
- [ ] **Step 4: Run tests.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(corpus): chunking, sqlite store, embedders and ingestion`.

---

### Task 5: Hybrid search

**Files:**
- Create: `uma/search.py`, `tests/test_search.py`

**Interfaces:**
- Consumes: `CorpusStore`, `Embedder`, `Chunk`, `Section`.
- Produces:
  - `SearchHit(chunk: Chunk, section: Section, score: float)`: frozen; `score` is the RRF score, higher is better.
  - `hybrid_search(store, embedder, query: str, *, k: int = 8, manual_id: str | None = None, candidates: int = 30) -> list[SearchHit]`.
  - `ensure_manual_coverage(ranked: list[SearchHit], k: int, min_ratio: float = 0.5) -> list[SearchHit]`.
  - `retrieve_for_rag(store, embedder, query: str, k: int) -> list[SearchHit]`, equal to `ensure_manual_coverage(hybrid_search(..., k=10_000), k)`.

The RRF and coverage rules are the algorithm, so here they are exactly:

```python
# RRF: for each chunk in the FTS top-`candidates` and the vector top-`candidates`
score[chunk_id] += 1 / (60 + rank)          # rank is 1-based within each list
# coverage: take ranked[:k]; then, for each manual absent from it whose best hit
# has score >= min_ratio * ranked[0].score, append that manual's best hit.
```

- [ ] **Step 1: Write failing tests**

```python
def test_keyword_and_semantic_both_contribute(...): ...   # a chunk matching only by exact term and one only by
                                                          # HashingEmbedder overlap both appear in top-k
def test_manual_filter(...): ...                          # manual_id="beta" -> all hits from beta
def test_rrf_scores_descending(...): ...
def test_coverage_adds_missing_manual():
    ranked = [hit("a", .03), hit("a", .029), hit("a", .028), hit("b", .02), hit("c", .01)]
    out = ensure_manual_coverage(ranked, k=2)
    assert [h.chunk.manual_id for h in out] == ["a", "a", "b"]   # c's .01 < .5 * .03
def test_empty_query_returns_empty(...): ...
```

- [ ] **Step 2: Run tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** Vector side: `scores = matrix @ embedder.embed([query])[0]`, then `argsort` descending. When `manual_id` is given, filter both lists to that manual's chunk IDs.
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat(search): hybrid BM25 + vector search with RRF and manual coverage`.

---

### Task 6: Sample corpus

**Files:**
- Create: `sample_manuals/nimbus-thermostat/{manual.yaml,getting-started.md,settings.md}`, `sample_manuals/nimbus-app/{manual.yaml,pairing.html,troubleshooting.html}`, `sample_manuals/nimbus-hub/{manual.yaml,hub-guide.md}`, `tests/test_sample_corpus.py`

**Interfaces:**
- Produces: a fictional "Nimbus" product family. All `visibility: external`, `owner: Nimbus Docs Team`, `base_url` omitted. Later tasks and the docs rely on these planted facts:
  - **Overlap: pairing the thermostat through the hub.** The steps are spread across all three manuals:
    - hub: hold the **Link** button 3 seconds until the LED blinks blue (`hub-guide.md` › "Pairing devices");
    - thermostat: **Menu › Settings › Connect › Hub** (`settings.md` › "Connect to a hub");
    - app: **Devices › Add › Thermostat**, then confirm the 6-digit code (`pairing.html` › "Add a thermostat").
  - **Gap:** no manual mentions voice assistants (Alexa, Google Assistant, Siri) or HomeKit.
  - **Contradiction: factory reset hold time.** The thermostat manual (`settings.md` › "Factory reset") says hold the reset pin **10 seconds**. The app's troubleshooting page (`troubleshooting.html` › "Reset the thermostat") says **5 seconds**.
  - **Duplicate heading:** `hub-guide.md` has two `## Reset` sections, under "Network" and under "Hardware".
  - **HTML boilerplate:** both HTML pages have a `<nav>`, a `<header>` and a `<footer>` to strip.
  - **Size:** each manual is 600–1,500 words of plausible content (installation, schedules, Wi-Fi, firmware, error codes E1–E4 in the thermostat manual), so retrieval has things to get wrong.

- [ ] **Step 1: Write failing test**

```python
def test_sample_corpus_planted_cases(tmp_store, embedder):
    r = ingest(Path("sample_manuals"), tmp_store, embedder)
    assert r.manuals == 3 and not r.skipped
    text = {s.id: s.text for s in tmp_store.sections()}
    assert any("10 seconds" in t for k, t in text.items() if k.startswith("nimbus-thermostat:"))
    assert any("5 seconds" in t for k, t in text.items() if k.startswith("nimbus-app:"))
    assert not any(w in t.lower() for t in text.values() for w in ("alexa", "homekit", "siri", "google assistant"))
    assert "nimbus-hub:hub-guide:reset-1" in text
    assert not any("©" in t for t in text.values())
```

- [ ] **Step 2: Run** `uv run pytest tests/test_sample_corpus.py -v`. Expected: FAIL.
- [ ] **Step 3: Write the seven files.**
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat: fictional Nimbus sample corpus with planted overlap, gap and contradiction`.

---

### Task 7: Strategy base types, status-tag filter and answering rules

**Files:**
- Create: `uma/strategies/__init__.py`, `uma/strategies/base.py`, `uma/strategies/rules.py`, `tests/test_base.py`

**Interfaces:**
- Consumes: `Usage` from Task 8. To avoid a circular order, define `Usage` in this task, in `uma/llm.py`, as a dataclass with `input_tokens`, `output_tokens`, `cache_read_tokens` and `cache_write_tokens` (all default 0) and an `__add__`. Task 8 adds the rest of `llm.py`.
- Produces:
  - `Status = Literal["answered", "not_covered", "contradiction_found"]`.
  - `Citation(manual_id: str, manual_title: str, section_id: str, heading_path: tuple[str, ...], cited_text: str)`: frozen.
  - `Metrics(latency_ms: int, usage: Usage, cost_usd: float | None, manuals_used: list[str], tool_calls: int = 0)`.
  - `Answer(text: str, citations: list[Citation], status: Status, metrics: Metrics)`.
  - Events: `TextDelta(text: str)`, `TraceStep(kind: str, detail: dict)`, `Final(answer: Answer)`, `Failed(message: str, hint_doc: str | None = None)`; `AnswerEvent` is their union.
  - `Strategy` protocol: `id: str`, `title: str`, `def answer(self, question: str) -> AsyncIterator[AnswerEvent]`.
  - `StatusTagFilter`: `feed(chunk: str) -> str` returns the text safe to show now; `finish() -> tuple[str, Status, bool]` returns the remaining visible text, the status, and whether a tag was found.
  - `strip_status(text: str) -> tuple[str, Status, bool]`: the same rule applied to a complete text.
  - `assemble_cited_text(content: list[dict], resolve: Callable[[dict], Citation | None]) -> tuple[str, list[Citation]]`.
    - Concatenates the `text` of the text blocks.
    - After each text block that has `citations`, appends ` [n]` markers. Citations are de-duplicated by `section_id`, and `n` is the 1-based index in the returned list.
  - `resolve_section_markers(text: str, lookup: Callable[[str], Citation | None]) -> tuple[str, list[Citation]]`. Replaces `[§<section_id>]` with `[n]` using the same de-duplication. Unknown IDs are removed.
  - `answer_to_dict(answer: Answer) -> dict`: a JSON-safe dict, with `heading_path` as a list and `usage` as a dict.
  - `rules.ANSWERING_RULES: str` and `rules.AGENTIC_ADDENDUM: str`.

- [ ] **Step 1: Write failing tests**

```python
def run(chunks):
    f = StatusTagFilter(); shown = "".join(f.feed(c) for c in chunks); rest, status, found = f.finish()
    return shown + rest, status, found

def test_tag_removed_and_detected():
    assert run(["Do X.\n<status>not_covered</status>"]) == ("Do X.\n", "not_covered", True)

def test_tag_split_across_chunks():
    assert run(["Do X. <sta", "tus>contradiction_fo", "und</status>\n"]) == ("Do X. ", "contradiction_found", True)

def test_literal_angle_bracket_passes_through():
    text, status, found = run(["If temperature < 5 °C, ", "use <b>frost</b> mode."])
    assert text == "If temperature < 5 °C, use <b>frost</b> mode." and status == "answered" and not found

def test_missing_tag_defaults_to_answered():
    assert run(["Plain answer."])[1:] == ("answered", False)

def test_invalid_status_value_defaults_to_answered():
    assert run(["x<status>maybe</status>"]) == ("x", "answered", False)

def test_assemble_cited_text_dedupes():
    blocks = [{"type": "text", "text": "Hold Link 3 s.", "citations": [{"k": "hub"}]},
              {"type": "text", "text": " Then open the app.", "citations": [{"k": "app"}, {"k": "hub"}]}]
    text, cits = assemble_cited_text(blocks, lambda c: CIT[c["k"]])
    assert text == "Hold Link 3 s. [1] Then open the app. [2][1]" and [c.section_id for c in cits] == ["hub-s", "app-s"]

def test_resolve_section_markers():
    text, cits = resolve_section_markers("Do A [§m:a:x]. Do B [§bogus].", lambda sid: CIT_BY_ID.get(sid))
    assert text == "Do A [1]. Do B ." and len(cits) == 1
```

- [ ] **Step 2: Run** `uv run pytest tests/test_base.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `StatusTagFilter` keeps back only a suffix that could still be a prefix of `<status>`, and, once inside a tag, everything up to `</status>`. Everything else is released immediately.
  - Write `ANSWERING_RULES` with this exact content (wording may be polished, but every rule must stay):

```text
You answer questions about a product using ONLY the manual content provided to you.
- Cite the manual content that supports every claim.
- If the procedure spans several manuals, give ONE ordered list of steps that combines them, citing each step's source.
- If the manuals do not answer the question, say so plainly and do not guess or use outside knowledge.
- If manuals contradict each other, say so explicitly, state both versions and cite both.
- Be concise. Use Markdown lists for procedures.
- End your answer with exactly one status tag on its own line:
  <status>answered</status> if the manuals answer the question,
  <status>not_covered</status> if they do not,
  <status>contradiction_found</status> if you found conflicting information.
```

  - `AGENTIC_ADDENDUM`: "You have tools to explore the manuals: list_manuals, search, read_section. Research before answering; read the sections you rely on. Cite with markers of the form [§<section_id>] right after each claim, using section ids returned by the tools."
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat(strategies): base types, status tag filter, citation helpers and answering rules`.

---

### Task 8: LLM wrapper and FakeLLM

**Files:**
- Modify: `uma/llm.py` (it holds `Usage` from Task 7)
- Create: `tests/test_llm.py`

**Interfaces:**
- Consumes: `Settings`.
- Produces:
  - `LLMResponse(content: list[dict], stop_reason: str, usage: Usage)`. `content` is the API content blocks as plain dicts, including thinking and tool_use blocks.
  - `TextChunk(text: str)` and `Completed(response: LLMResponse)`.
  - `LLM` protocol:
    - `def stream(self, *, system: str, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[TextChunk | Completed]`;
    - `async def count_tokens(self, *, system: str, messages: list[dict]) -> int`.
  - `LLMError(Exception)`: carries a user-facing message. Raised for missing credentials (`"ANTHROPIC_API_KEY is not set. Add it to .env and restart."`), authentication failures, and API errors left after the SDK's retries.
  - `AnthropicLLM(settings: Settings, client: anthropic.AsyncAnthropic | None = None)`.
  - `FakeLLM(responses: list[LLMResponse], token_count: int = 1_000)`.
    - Yields each text block's text as 2 `TextChunk`s (split in the middle), then `Completed`.
    - Keeps its script in the public attribute `.responses` and records every call's keyword arguments in `.calls: list[dict]`.
    - Raises `AssertionError` when its scripted responses run out.
  - Helper `text_response(text: str, citations: list[dict] | None = None, usage: Usage = Usage(10, 5)) -> LLMResponse` for tests.

- [ ] **Step 1: Write failing tests**

```python
async def test_fake_llm_streams_then_completes():
    llm = FakeLLM([text_response("Hello world")])
    events = [e async for e in llm.stream(system="s", messages=[])]
    assert "".join(e.text for e in events if isinstance(e, TextChunk)) == "Hello world"
    assert isinstance(events[-1], Completed) and llm.calls[0]["system"] == "s"

async def test_anthropic_llm_request_shape():
    client = RecordingClient(final_message=fake_sdk_message())   # test double for client.beta.messages.stream
    llm = AnthropicLLM(load_settings({}), client=client)
    _ = [e async for e in llm.stream(system="s", messages=[{"role": "user", "content": "q"}])]
    kw = client.last_kwargs
    assert kw["model"] == "claude-sonnet-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "medium"} and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["extra_body"] == {"fallbacks": "default"} and "tool_choice" not in kw

async def test_missing_api_key_raises_llm_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        _ = [e async for e in AnthropicLLM(load_settings({})).stream(system="s", messages=[])]
```

- [ ] **Step 2: Run** `uv run pytest tests/test_llm.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `AnthropicLLM.stream`.**
  - Use `async with client.beta.messages.stream(model=..., max_tokens=16000, system=..., messages=..., tools=tools or omit, thinking={"type": "adaptive"}, output_config={"effort": settings.effort}, betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"}, cache_control={"type": "ephemeral"})`.
  - Yield a `TextChunk` for each item of `stream.text_stream`.
  - Then call `get_final_message()` and convert `content` with `b.model_dump(exclude_none=True)` and `usage` (`cache_read_input_tokens`, `cache_creation_input_tokens`).
  - **Missing key:** check `ANTHROPIC_API_KEY` before creating the client. If it's unset, run `ant auth status`; when no profile is active, raise `LLMError`.
  - **Errors:** map `anthropic.AuthenticationError`, then `anthropic.RateLimitError`, then `anthropic.APIStatusError`, then `anthropic.APIConnectionError` (most specific first) to `LLMError` with readable messages.
  - **`count_tokens`:** use `client.messages.count_tokens(model=..., system=..., messages=...)` and return `.input_tokens`.
  - **Check:** confirm these SDK names against `python/claude-api/README.md` and `streaming.md` in the claude-api skill before writing the code.
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat(llm): Anthropic wrapper with fallback, caching and a scripted FakeLLM`.

---

### Task 9: Whole-context strategy

**Files:**
- Create: `uma/strategies/whole_context.py`, `tests/test_whole_context.py`
- Modify: `uma/strategies/base.py` (add `run_single_call`)

**Interfaces:**
- Consumes: `CorpusStore`, `LLM`, `Settings`, the base helpers, `ANSWERING_RULES`, `cost_usd`.
- Produces:
  - `WholeContextStrategy(store: CorpusStore, llm: LLM, settings: Settings)`, with `id = "whole_context"` and `title = "Whole-context"`.
  - `build_documents(manuals: list[ManualRecord], sections: list[Section]) -> list[dict]`. Each manual becomes:
    `{"type": "document", "source": {"type": "content", "content": [{"type": "text", "text": "<heading path joined by ' › '>\n\n<section text>"}, ...]}, "title": <manual title>, "citations": {"enabled": True}}`.
    The last document also gets `"cache_control": {"type": "ephemeral"}`.
  - `CORPUS_TOO_LARGE_DOC = "/docs/strategies/1-whole-context.md#avoid-when"`.

- [ ] **Step 1: Check the citation shapes.** WebFetch the citations page listed in the claude-api skill's `shared/live-sources.md`. Confirm the custom-content document source shape and the `content_block_location` fields (`document_index`, `start_block_index`, `cited_text`). If the field names differ, use the documented ones in Step 3 and the tests.
- [ ] **Step 2: Write failing tests** (sample corpus ingested with `HashingEmbedder`):

```python
async def test_streams_text_and_final_with_citations(sample_store):
    cit = {"type": "content_block_location", "document_index": 1, "start_block_index": 0, "end_block_index": 1,
           "cited_text": "Hold the Link button"}
    llm = FakeLLM([text_response("Hold Link 3 s.", citations=[cit]), ], token_count=40_000)
    # second text block with the status tag is part of the same response:
    llm.responses[0].content.append({"type": "text", "text": "\n<status>answered</status>"})
    events = [e async for e in WholeContextStrategy(sample_store, llm, load_settings({})).answer("pair?")]
    final = events[-1].answer
    assert final.status == "answered" and final.text.strip() == "Hold Link 3 s. [1]"
    assert final.citations[0].manual_id == "nimbus-hub"          # manuals ordered by id: app, hub, thermostat
    assert "<status>" not in "".join(e.text for e in events if isinstance(e, TextDelta))

async def test_request_contains_every_section_and_cache_breakpoint(sample_store): ...
    # llm.calls[0]["messages"][0]["content"]: 3 documents then the question text block;
    # total content blocks == len(sample_store.sections()); only the last document has cache_control

async def test_too_large_corpus_fails_with_hint(sample_store):
    llm = FakeLLM([], token_count=900_000)
    events = [e async for e in WholeContextStrategy(sample_store, llm, load_settings({})).answer("q")]
    assert isinstance(events[-1], Failed) and "900,000" in events[-1].message
    assert events[-1].hint_doc == CORPUS_TOO_LARGE_DOC

async def test_token_count_cached_in_store(sample_store): ...   # second answer() does not call count_tokens again

async def test_refusal_becomes_failed(sample_store): ...         # stop_reason "refusal" -> Failed("The model declined this question")

async def test_llm_error_becomes_failed(sample_store): ...       # LLMError("ANTHROPIC_API_KEY ...") -> Failed with that message
```

- [ ] **Step 3: Implement `answer`.**
  1. Use `store.corpus_token_count()`, or `llm.count_tokens(system, messages with the question "?")` followed by `store.set_token_count(None, n)`.
  2. Fail if the count is over `settings.whole_context_max_tokens`.
  3. Stream through `StatusTagFilter`, emitting `TextDelta`s.
  4. On `Completed`: check `stop_reason`, then `assemble_cited_text`, then `strip_status` on the assembled text.
  5. Build `Metrics`: latency from `time.perf_counter`, `cost_usd`, `manuals_used` = distinct citation manual titles.
  6. Emit `Final`.
  - Catch `LLMError` and emit `Failed(str(e))`.
  - Put the per-call structure (stream, filter, assemble, metrics) in a reusable helper `run_single_call(llm, system, messages, resolve, started) -> AsyncIterator[AnswerEvent]` in `base.py`. Task 10 reuses it.
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat(strategies): whole-context strategy with native citations and prompt caching`.

---

### Task 10: RAG strategy

**Files:**
- Create: `uma/strategies/rag.py`, `tests/test_rag.py`

**Interfaces:**
- Consumes: `retrieve_for_rag` (Task 5), `run_single_call` (Task 9).
- Produces: `RagStrategy(store, embedder, llm, settings)`, with `id = "rag"` and `title = "RAG"`.
  - **Retrieval:** one document per hit, in rank order:
    `{"type": "document", "source": {"type": "content", "content": [{"type": "text", "text": <chunk text>}]}, "title": f"{manual title} — {' › '.join(heading_path)}", "citations": {"enabled": True}}`.
  - **No cache breakpoint**, because the content changes with every question.
  - **Trace:** before calling the LLM, emit `TraceStep("retrieved", {"chunks": [{"section_id", "manual_title", "heading_path": list, "score": float}]})`.

- [ ] **Step 1: Write failing tests**

```python
async def test_retrieval_trace_then_answer(sample_store, embedder):
    llm = FakeLLM([text_response("Answer [cited].\n<status>answered</status>",
                                 citations=[{"type": "content_block_location", "document_index": 0,
                                             "start_block_index": 0, "end_block_index": 1, "cited_text": "x"}])])
    events = [e async for e in RagStrategy(sample_store, embedder, llm, load_settings({})).answer("How do I pair the thermostat with the hub?")]
    assert isinstance(events[0], TraceStep) and events[0].kind == "retrieved"
    sent_docs = [b for b in llm.calls[0]["messages"][0]["content"] if b["type"] == "document"]
    assert len(sent_docs) == len(events[0].detail["chunks"]) and len(sent_docs) >= 8
    assert events[-1].answer.citations[0].section_id == events[0].detail["chunks"][0]["section_id"]

async def test_rag_uses_settings_top_k(sample_store, embedder): ...   # RAG_TOP_K=3 -> 3 docs + coverage additions only
async def test_rag_uses_shared_rules(sample_store, embedder): ...    # llm.calls[0]["system"] starts with ANSWERING_RULES
```

- [ ] **Step 2: Run tests.** Expected: FAIL.
- [ ] **Step 3: Implement** using `run_single_call`, with `resolve` mapping `document_index` to its hit's section.
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat(strategies): RAG strategy over hybrid search`.

---

### Task 11: Agentic strategy and ADR 0012

**Files:**
- Create: `uma/strategies/agentic.py`, `tests/test_agentic.py`, `docs/adr/0012-citation-mechanism-per-strategy.md`
- Modify: `docs/adr/README.md` (add the 0012 row), `uma/llm.py` (add `tool_use_response`)

**Interfaces:**
- Consumes: `hybrid_search`, `CorpusStore`, `LLM`, `resolve_section_markers`, `AGENTIC_ADDENDUM`.
- Produces: `AgenticStrategy(store, embedder, llm, settings)`, with `id = "agentic"` and `title = "Agentic"`.
- `TOOLS: list[dict]`. Three tools, each with `"strict": True` and `additionalProperties: false`:
  - `list_manuals()`: returns one line per manual, `id | title | owner | N sections`.
  - `search(query: str, manual_id: str | null)`: returns up to 8 lines, `section_id | manual title | heading path | first 300 chars of the chunk`, from `hybrid_search`.
  - `read_section(section_id: str)`: returns the heading path and the full text, or an `is_error` result `"Unknown section_id: <id>"`.

**Loop**. This is the algorithm, so it's pinned:

```text
messages = [user: question]; calls = 0
repeat up to agent_max_tool_calls + 2 turns:
    stream turn (system = ANSWERING_RULES + "\n\n" + AGENTIC_ADDENDUM, tools = TOOLS) through StatusTagFilter
    append assistant turn with response.content unchanged
    if stop_reason == "refusal": Failed("The model declined this question")
    if stop_reason != "tool_use": finalise from this turn's text blocks -> Final
    results = []
    for each tool_use block: calls += 1
        if calls > agent_max_tool_calls: result = is_error "Tool budget exhausted. Answer now."
        else: run tool; emit TraceStep("tool_call", {"name", "input", "summary": first line of result or "error"})
        results.append(tool_result)
    if calls >= agent_max_tool_calls: results.append(text block "Tool budget reached. Answer now with what you have.")
    append ONE user message with all results
Failed("The agent did not finish within its tool budget")
```

- **Final answer:** the last turn's text, then `strip_status`, then `resolve_section_markers`.
- **Metrics:** usage summed across turns; `tool_calls = calls`.

- [ ] **Step 1: Write failing tests**

```python
async def test_tool_loop_then_cited_answer(sample_store, embedder):
    llm = FakeLLM([tool_use_response("search", {"query": "pair hub", "manual_id": None}),
                   tool_use_response("read_section", {"section_id": "nimbus-hub:hub-guide:pairing-devices"}),
                   text_response("Hold Link 3 s [§nimbus-hub:hub-guide:pairing-devices].\n<status>answered</status>")])
    events = [e async for e in AgenticStrategy(sample_store, embedder, llm, load_settings({})).answer("pair?")]
    traces = [e for e in events if isinstance(e, TraceStep)]
    assert [t.detail["name"] for t in traces] == ["search", "read_section"]
    final = events[-1].answer
    assert final.text.strip() == "Hold Link 3 s [1]." and final.metrics.tool_calls == 2
    assert final.citations[0].section_id == "nimbus-hub:hub-guide:pairing-devices"
    # all tool_results of a turn are in ONE user message; assistant content echoed unchanged
    assert llm.calls[1]["messages"][1]["content"] == llm.responses[0].content

async def test_unknown_section_returns_error_result(...): ...      # is_error True, loop continues
async def test_budget_cap(...):                                    # AGENT_MAX_TOOL_CALLS=2, model keeps calling tools
    ...                                                            # 3rd call gets "Tool budget exhausted" result;
                                                                   # ends Failed after max+2 turns if it never answers
async def test_tools_are_strict_and_not_forced(...): ...           # every tool strict True; "tool_choice" absent in calls
```

- [ ] **Step 2: Run tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** Add the helper `tool_use_response(name, input, id=...)` to `uma/llm.py` next to `text_response`.
- [ ] **Step 4: Write ADR 0012, "Citation mechanism per strategy".**
  - Whole-context and RAG use Claude's native document citations. The `content_block_location` maps exactly to a section.
  - The agentic strategy reads content through tool results, so it cites with `[§section_id]` markers that the code resolves.
  - Options considered:
    - native citations everywhere, through `search_result` blocks in tool results: more API surface, and a less transparent lesson;
    - markers everywhere: loses the native-citation lesson and its exact quoted text.
  - Consequence: the agentic column shows citations without `cited_text` quotes.
- [ ] **Step 5: Run tests.** Expected: pass.
- [ ] **Step 6: Commit**: `feat(strategies): agentic strategy with tool loop; ADR 0012 citation mechanisms`.

---

### Task 12: Question log, votes and runner

**Files:**
- Create: `uma/log.py`, `uma/runner.py`, `tests/test_log.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `Answer`, `answer_to_dict`, `Strategy`, the events.
- Produces:
  - `VoteError(ValueError)`.
  - `Log(db_path: Path)` creates the `questions`, `answers` and `votes` tables from spec §7, with methods:
    - `create_question(text: str, blind: bool) -> str`: a uuid4 hex string;
    - `get_question(question_id: str) -> dict | None`;
    - `save_answer(question_id: str, strategy_id: str, *, answer: Answer | None, error: str | None, trace: list[dict]) -> None`;
    - `answers_for(question_id: str) -> dict[str, dict]`: keyed by strategy ID; each dict has `status`, `text`, `citations` (list), `trace` (list), `error`, metrics fields, and `answer` (as `answer_to_dict` output, or None);
    - `upsert_vote(question_id: str, strategy_id: str, stars: int, blind: bool) -> None`. Raises `VoteError` when stars aren't between 1 and 5, the question is unknown, the answer is missing, or the answer failed;
    - `votes(mode: Literal["all", "blind", "labelled"] = "all") -> list[dict]`: each has `question_id`, `strategy`, `stars`, `blind`;
    - `all_answers() -> list[dict]`;
    - `reset_votes() -> None`;
    - `export_rows() -> list[dict]`: one row per vote, with `question_text`, `strategy`, `stars`, `blind`, `voted_at`, `status`, `latency_ms`, `cost_usd`, `input_tokens`, `output_tokens`.
  - `run_question(question_id: str, question: str, strategies: list[Strategy], log: Log, timeout_s: float) -> AsyncIterator[dict]`. Yields SSE payloads:
    - `{"strategy", "type": "delta", "text"}`;
    - `{"strategy", "type": "trace", "kind", "detail"}`;
    - `{"strategy", "type": "final", "answer": answer_to_dict(...)}`;
    - `{"strategy", "type": "failed", "message", "hint_doc"}`;
    - finally `{"type": "done"}`.
    - It persists every strategy's outcome before yielding `done`.
    - A strategy that raises yields `failed` with `"Unexpected error: <ExceptionType>"`.
    - A strategy that times out yields `failed` with `"Timed out after 90 s"` (the configured value).

- [ ] **Step 1: Write failing tests**

```python
def test_vote_rejects_out_of_range(log_with_answers):
    for stars in (0, 6):
        with pytest.raises(VoteError): log_with_answers.upsert_vote(QID, "rag", stars, False)
def test_vote_on_failed_answer_rejected(log_with_answers):
    with pytest.raises(VoteError): log_with_answers.upsert_vote(QID, "whole_context", 3, False)   # saved with error
def test_vote_upsert_replaces(log_with_answers):
    log_with_answers.upsert_vote(QID, "rag", 2, False); log_with_answers.upsert_vote(QID, "rag", 5, True)
    assert log_with_answers.votes() == [{"question_id": QID, "strategy": "rag", "stars": 5, "blind": True}]
def test_votes_mode_filter(...): ...
def test_reset_votes_keeps_answers(...): ...

async def test_runner_runs_in_parallel_and_persists(tmp_path):
    slow, fast = ScriptedStrategy("a", delay=0.2, text="A"), ScriptedStrategy("b", delay=0.0, text="B")
    events = [e async for e in run_question(qid, "q", [slow, fast], log, timeout_s=5)]
    finals = [e["strategy"] for e in events if e["type"] == "final"]
    assert finals == ["b", "a"] and events[-1] == {"type": "done"}
    assert set(log.answers_for(qid)) == {"a", "b"}
async def test_runner_isolates_exceptions(...): ...   # raising strategy -> failed event; others still final
async def test_runner_timeout(...): ...               # timeout_s=0.05 with delay=1 -> "Timed out after 0.05 s"
```

- [ ] **Step 2: Run tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **Runner:** one `asyncio.Task` per strategy pushes payloads into a shared `asyncio.Queue`. Wrap each strategy's iteration in `asyncio.timeout(timeout_s)`. A sentinel per strategy marks completion. Save each strategy's outcome to the log as it finishes. Collect `TraceStep` details per strategy for the `trace` column.
  - **Format the timeout number with `:g`.**
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat: question log with vote validation and parallel strategy runner`.

---

### Task 13: Leaderboard

**Files:**
- Create: `uma/leaderboard.py`, `tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `Log`.
- Produces:
  - `StrategyRow(strategy_id: str, title: str, avg_stars: float | None, votes: int, distribution: dict[int, int], wins: int, avg_latency_ms: float | None, avg_cost_usd: float | None, not_covered_rate: float | None, errors: int)`.
  - `compute_leaderboard(log: Log, titles: dict[str, str], mode: Literal["all", "blind", "labelled"] = "all") -> list[StrategyRow]`.
  - `recent_questions(log: Log, mode: str = "all", limit: int = 20) -> list[dict]`: each has `question_id`, `text`, `asked_at`, `ratings: dict[strategy, stars]`, `spread`.

Rules (pinned):
- `avg_stars`, `votes`, `distribution` and `wins` use only votes that match `mode`. `distribution` always has keys 1–5.
- A question counts towards **wins** only if at least 2 strategies were rated on it. Every strategy with the highest rating gets +1, so ties give a win to each tied strategy.
- `avg_latency_ms`, `avg_cost_usd` and `not_covered_rate` are computed over all non-failed answers, whatever the `mode`. `errors` counts failed answers.
- **Sort:** `avg_stars` descending, `None` last, then `votes` descending. Every strategy in `titles` appears even with no data.
- `recent_questions` includes only questions with at least one vote in `mode`, sorted by `spread` (max minus min stars) descending, then `asked_at` descending.

- [ ] **Step 1: Write failing tests**

```python
def test_averages_distribution_and_ranking(seeded_log):
    # votes: whole_context 5,4 ; rag 3,3 ; agentic 4,5 (agentic one blind)
    rows = compute_leaderboard(seeded_log, TITLES)
    assert [r.strategy_id for r in rows][0] in {"whole_context", "agentic"} and rows[-1].strategy_id == "rag"
    assert rows[-1].distribution == {1: 0, 2: 0, 3: 2, 4: 0, 5: 0}

def test_wins_with_ties(seeded_log):
    # q1: wc 5, rag 3, ag 5  -> wc+1, ag+1 ; q2: wc 4, rag 3, ag 4 (blind) -> wc+1, ag+1 ; q3: only rag rated -> no win
    rows = {r.strategy_id: r for r in compute_leaderboard(seeded_log, TITLES)}
    assert (rows["whole_context"].wins, rows["agentic"].wins, rows["rag"].wins) == (2, 2, 0)

def test_blind_filter(seeded_log):
    rows = {r.strategy_id: r for r in compute_leaderboard(seeded_log, TITLES, mode="blind")}
    assert rows["agentic"].votes == 1 and rows["rag"].avg_stars is None

def test_errors_and_not_covered_rate(seeded_log): ...
def test_empty_log_lists_all_strategies(tmp_path): ...
def test_recent_questions_sorted_by_spread(seeded_log): ...
```

- [ ] **Step 2: Run tests.** Expected: FAIL.
- [ ] **Step 3: Implement** (plain Python over `log.votes(mode)` and `log.all_answers()`).
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Commit**: `feat: leaderboard aggregation with wins, ties and blind filter`.

---

### Task 14: Web API, SSE and CLI

**Files:**
- Create: `uma/web.py`, `uma/__main__.py`, `tests/test_web.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `create_app(settings: Settings, *, llm: LLM | None = None, embedder: Embedder | None = None) -> FastAPI`. The defaults are `AnthropicLLM(settings)` and `FastEmbedEmbedder()`, the latter loaded lazily on first search.
  - `STRATEGY_ORDER = ["whole_context", "rag", "agentic"]`.

| Route | Behaviour |
|-------|-----------|
| `GET /` | `static/index.html` |
| `GET /leaderboard` | `static/leaderboard.html` |
| `/static/*` | `uma/static` |
| `/docs/*` | the repo `docs/` folder, served raw |
| `GET /api/strategies` | `[{"id", "title", "flow": "/static/diagrams/<id>-flow.mmd", "sequence": "/static/diagrams/<id>-sequence.mmd", "doc": "/docs/strategies/<n>-<slug>.md"}]` in `STRATEGY_ORDER` |
| `GET /api/status` | `{"corpus_ready": bool, "manuals": [{"id","title","sections"}], "model": str}` |
| `POST /api/questions` `{"text": str, "blind": bool}` | 422 for empty or whitespace text; 409 `{"detail": "No manuals ingested. Run: uv run python -m uma ingest"}` when the store is empty; otherwise `{"question_id"}` |
| `GET /api/questions/{id}/stream` | 404 for an unknown ID. `text/event-stream`, `data: <json>\n\n` per payload from `run_question`. If answers already exist, replays the stored `final`/`failed` payloads and then `done`, without re-running. |
| `GET /api/sections/{section_id}` | `{"id","manual_title","heading_path","text","source_url"}` or 404 |
| `POST /api/votes` `{"question_id","strategy","stars","blind"}` | 204; `VoteError` → 400 `{"detail": str(e)}` |
| `GET /api/leaderboard?mode=all\|blind\|labelled` | `{"rows": [StrategyRow as dict], "recent": recent_questions(...)}` |
| `GET /api/export.csv` | `text/csv` attachment `uma-votes.csv` from `log.export_rows()` |
| `POST /api/reset-votes` | 204 |

  - CLI `python -m uma`:
    - loads `.env` with python-dotenv;
    - `ingest [--manuals-dir PATH] [--sample]` (`--sample` uses `sample_manuals/`) prints the `IngestReport`;
    - `serve [--host 127.0.0.1] [--port 8000]` runs Uvicorn.

- [ ] **Step 1: Write failing tests** (`TestClient`, `FakeLLM`, `HashingEmbedder`, sample corpus ingested into `tmp_path`):

```python
def test_ask_and_stream(client_with_fake_llm):
    qid = client.post("/api/questions", json={"text": "How do I pair?", "blind": False}).json()["question_id"]
    with client.stream("GET", f"/api/questions/{qid}/stream") as r:
        payloads = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
    assert payloads[-1] == {"type": "done"}
    assert {p["strategy"] for p in payloads if p["type"] in ("final", "failed")} == set(STRATEGY_ORDER)

def test_stream_replay_does_not_rerun(...): ...          # second GET -> same finals, FakeLLM.calls unchanged
def test_empty_question_422(...): ...
def test_empty_corpus_409(...): ...
def test_post_vote_invalid_returns_400(...):             # stars 6 -> 400; vote on failed answer -> 400
    ...
def test_vote_then_leaderboard(...): ...                 # rows contain the vote; mode=blind excludes labelled vote
def test_export_csv_header(...): ...                     # first line has question_text,strategy,stars,blind,...
def test_section_endpoint(...): ...
def test_missing_api_key_each_column_failed(monkeypatch, ...): ...  # real AnthropicLLM, no key -> 3 failed payloads
                                                                    # mentioning ANTHROPIC_API_KEY, no 500
# test_cli.py
def test_ingest_sample_cli(tmp_path, monkeypatch): ...   # UMA_DB_PATH=tmp; main(["ingest", "--sample"]) with
                                                         # embedder patched to HashingEmbedder; prints "3 manuals"
```

- [ ] **Step 2: Run tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** Build the strategies once per app, with fixed objects `CorpusStore(settings.db_path)` and `Log(settings.db_path)`. Make the CLI testable through `main(argv: list[str] | None = None) -> int`.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: the whole suite passes.
- [ ] **Step 5: Commit**: `feat: FastAPI app with SSE streaming, votes, leaderboard API and CLI`.

---

### Task 15: Ask page

**Files:**
- Create: `uma/static/index.html`, `uma/static/app.js`, `uma/static/style.css`
- Test: `tests/test_static.py`

**Interfaces:**
- Consumes: the Task 14 API.
- Produces: element IDs used by the tests and the docs: `#question-form`, `#question-input`, `#mode-toggle`, `#columns`, `#corpus-warning`. Each column is a `.column[data-strategy]` containing `.answer`, `.status-badge`, `.metrics`, `.trace` (a `<details>`), `.how-it-works` (a button), `.stars` (5 buttons with `data-stars`), and `.reveal` (shown only in blind mode).

Behaviour (spec §6.1):
- **On load:** `GET /api/status`. Show `#corpus-warning` with the ingest command when `corpus_ready` is false.
- **Mode:** read from and write to `localStorage["uma-mode"]` (`"labelled"` by default), with every access wrapped in `try/catch`.
  - Labelled mode: fixed order Whole-context · RAG · Agentic.
  - Blind mode: shuffle the columns with Fisher–Yates per question and label them "Answer X / Y / Z". Reveal a column's name after it's rated or when its Reveal button is clicked.
- **Submit:** `POST /api/questions`, then open an `EventSource` on the stream.
  - `delta`: append to `.answer` as text.
  - `trace`: add a list item to `.trace`.
  - `final`: replace `.answer` with `DOMPurify.sanitize(marked.parse(answer.text))`. Turn each `[n]` into a button that opens a side panel loaded from `GET /api/sections/{id}`, with an "Open original" link when `source_url` is set. Fill the badge (`answered` ✓, `not_covered`, `contradiction_found` ⚠) and the metrics: `"{latency s} s · {tokens in}/{tokens out} tok · ${cost:.4f} · {manuals}"`.
  - `failed`: show the message, with a link to `hint_doc` when present, and disable the stars.
  - `done`: close the `EventSource`.
- **Stars:** clicking sends `POST /api/votes` and highlights the chosen star. Ratings can be changed until the next question.
- **How it works:** a `<dialog>` that fetches the column's `flow` and `sequence` `.mmd` files and renders them with `mermaid.render`, plus a link to `doc`.
- **Libraries:** load mermaid, marked and DOMPurify from `cdn.jsdelivr.net/npm/` with pinned major versions.
- **Layout:** three columns at 1000 px and wider, stacked on narrow screens. Light and dark themes come from CSS variables and `prefers-color-scheme`.

- [ ] **Step 1: Write failing test.** `test_index_has_required_elements`: `GET /` contains every ID and class listed above, and `/static/app.js` returns 200.
- [ ] **Step 2: Run** `uv run pytest tests/test_static.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the three files.**
- [ ] **Step 4: Run tests.** Expected: pass.
- [ ] **Step 5: Check in the browser.**
  - Run `uv run python -m uma ingest --sample && uv run python -m uma serve`, with a real `ANTHROPIC_API_KEY`.
  - Ask "How do I pair the thermostat with the hub?" and confirm:
    1. the three columns stream;
    2. the citation buttons open the section panel;
    3. the badges and metrics appear;
    4. the stars save, and changing them works;
    5. blind mode shuffles the columns and hides the names until you rate or reveal;
    6. "How it works" renders the diagrams (after Task 17; until then, check that the dialog opens).
  - If there's no API key, confirm that each column shows the `ANTHROPIC_API_KEY` message.
- [ ] **Step 6: Commit**: `feat(ui): ask page with streaming columns, citations, ratings and blind mode`.

---

### Task 16: Leaderboard page

**Files:**
- Create: `uma/static/leaderboard.html`, `uma/static/leaderboard.js`
- Modify: `uma/static/style.css`, `tests/test_static.py`

**Interfaces:**
- Consumes: `GET /api/leaderboard`, `/api/export.csv`, `POST /api/reset-votes`.
- Produces: IDs `#mode-filter` (a select: all / blind / labelled), `#leaderboard-table`, `#recent-table`, `#export-csv`, `#reset-votes`.

Behaviour (spec §6.2):
- **Leaderboard table** columns: Rank, Strategy, Avg ★ (one decimal place, `–` for none), Votes, ★ distribution (an inline bar of 5 segments with counts), Wins, Avg time (s), Avg cost ($, 4 decimal places), Not covered (%), Errors.
- **Recent table:** question text, then one rating per strategy, then the spread.
- **Reset:** asks for confirmation with `confirm()`, then reloads the tables.
- **Navigation:** links between `/` and `/leaderboard` in both page headers.

- [ ] **Step 1: Write failing test.** `test_leaderboard_page_has_required_elements`.
- [ ] **Step 2: Run tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and check in the browser.**
  - Rate a few answers in both modes, open `/leaderboard`, and switch the filter.
  - Export the CSV and open it.
  - Reset, and confirm the tables empty.
- [ ] **Step 5: Commit**: `feat(ui): leaderboard page with filter, export and reset`.

---

### Task 17: Diagrams and architecture overview

**Files:**
- Create:
  - `uma/static/diagrams/overview.mmd`;
  - `{whole_context,rag,agentic}-flow.mmd` and `{whole_context,rag,agentic}-sequence.mmd` in the same folder;
  - `docs/architecture/overview.md`;
  - `tests/test_docs.py`.

**Interfaces:**
- Produces: the diagram files the API's `/api/strategies` and the "How it works" dialog expect.

Diagram content (pinned):
- **`overview.mmd`:** the spec §4 flowchart. Manual files → Ingestion → SQLite (corpus); Web UI → FastAPI → three strategies → SSE back to the UI; votes → SQLite (log).
- **`*-flow.mmd`** (flowcharts; components that information passes through, edges labelled with what travels):
  - whole-context: Question + all sections → Claude (cached prefix) → answer + citations → status filter → UI.
  - rag: Question → embedder + FTS5 → RRF → coverage rule → top-k chunks → Claude → answer + citations → UI.
  - agentic: Question → Claude ⇄ tools (`list_manuals`, `search` → hybrid search, `read_section` → SQLite) for at most 8 calls → answer with `[§id]` markers → marker resolver → UI.
- **`*-sequence.mmd`** (sequence diagrams of one question; participants are UI, FastAPI/runner, Strategy, plus as relevant SQLite, Search, Claude API):
  - **whole-context:** show `count_tokens` on the first call only, and a cache write on the first question versus a cache read afterwards.
  - **rag:** show the retrieval trace event being sent before the Claude call.
  - **agentic:** use a `loop` block for the tool calls and an `alt` block for the budget being reached.

- **`docs/architecture/overview.md`:** embeds `overview.mmd`, then lists each unit from spec §4.1 linked to its file, then walks through the data flow for ingestion and for one question, then links to every ADR.

- [ ] **Step 1: Write failing tests**

```python
def test_strategy_docs_embed_current_diagrams():
    for sid, doc in [("whole_context", "1-whole-context.md"), ("rag", "2-rag.md"), ("agentic", "3-agentic.md")]:
        text = Path("docs/strategies", doc).read_text()
        for kind in ("flow", "sequence"):
            src = Path(f"uma/static/diagrams/{sid}-{kind}.mmd").read_text().strip()
            assert f"```mermaid\n{src}\n```" in text, f"{doc} is missing the current {kind} diagram"

def test_overview_embeds_diagram():
    src = Path("uma/static/diagrams/overview.mmd").read_text().strip()
    assert f"```mermaid\n{src}\n```" in Path("docs/architecture/overview.md").read_text()

def test_every_api_diagram_exists(): ...   # each path returned by /api/strategies resolves to a file
```

- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -v`. Expected: FAIL. The strategy docs test keeps failing until Task 18.
- [ ] **Step 3: Write the seven `.mmd` files and `overview.md`.** Check that each diagram renders, either with `npx -y @mermaid-js/mermaid-cli -i <file> -o /tmp/x.svg` if Node is available, or in the app's "How it works" dialog.
- [ ] **Step 4: Run** `uv run pytest tests/test_docs.py::test_overview_embeds_diagram tests/test_docs.py::test_every_api_diagram_exists -v`. Expected: pass.
- [ ] **Step 5: Commit**: `docs: architecture overview and Mermaid diagrams for each strategy`.

---

### Task 18: Strategy explainers, decision guide and demo questions

**Files:**
- Create: `docs/strategies/1-whole-context.md`, `docs/strategies/2-rag.md`, `docs/strategies/3-agentic.md`, `docs/choosing-a-strategy.md`, `docs/demo-questions.md`

Each explainer uses these headings, in this order, so `#avoid-when` and the other anchors are stable:
`## In one paragraph`, `## Diagrams`, `## Step by step`, `## Prefer when`, `## Avoid when`, `## Cost and latency`, `## Typical failure modes`, `## What to look for in the demo`.
- **Diagrams:** both `.mmd` files embedded verbatim.
- **Step by step:** each step links to a file and function, for example `[build_documents](../../uma/strategies/whole_context.py)`.

Pinned guidance (prose may expand on it):

| | Prefer when | Avoid when |
|---|---|---|
| Whole-context | The corpus fits comfortably in the context window (up to roughly a few hundred thousand tokens); questions often span documents; completeness and honest "not covered" matter; the corpus changes rarely, so caching pays off | The corpus exceeds the context limit or grows unbounded; there's high query volume with a frequently changing corpus (cache misses re-bill everything); latency or cost per question must be minimal; only a tiny slice is ever relevant |
| RAG | Large or growing corpora; high query volume; questions answerable from a few passages; predictable cost and latency matter | Answers need information spread across many documents; "not covered" must be trustworthy, because "not retrieved" looks the same as "not there"; vocabulary differs from the user's wording and the embeddings are weak |
| Agentic | Large corpora where questions need multi-step research; a visible research trail is valuable; the questions are varied and hard to anticipate | Latency-sensitive chat; strict cost ceilings; simple lookups (it over-researches); results must be the same for the same question |

- **Cost and latency:** use the ADR 0011 prices and the metrics footer fields.
- **Failure modes:**
  - whole-context: the context limit, slow and expensive first calls, lost-in-the-middle on very long contexts;
  - RAG: retrieval misses, chunk boundaries splitting procedures, coverage gaps;
  - agentic: stopping too early, budget exhaustion, query loops.
- **`choosing-a-strategy.md`:** a decision matrix with rows corpus size, change rate, query volume, cross-document need, honesty need, latency budget, cost budget, and transparency, giving a rating per strategy. Below it, a short decision flowchart in Mermaid. Link it from the README.
- **`demo-questions.md`:** the showcase questions, each with the expected behaviour per strategy and what it teaches:
  1. "How do I pair the thermostat with the hub?" (overlap across all three manuals);
  2. "How do I control the thermostat with Alexa?" (gap, expecting `not_covered`);
  3. "How long do I hold the reset button to factory-reset the thermostat?" (contradiction, 10 s versus 5 s);
  4. "What does error E3 mean?" (a single-passage lookup where RAG should be cheapest);
  5. "Give me a complete first-day setup checklist" (broad synthesis).

- [ ] **Step 1: Write the five documents.**
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -v`. Expected: all pass, now including `test_strategy_docs_embed_current_diagrams`.
- [ ] **Step 3: Check that all links resolve.** Run `uv run python -c "import re,pathlib,sys; bad=[(p,l) for p in pathlib.Path('docs').rglob('*.md') for l in re.findall(r'\]\((?!http|#)([^)#]+)', p.read_text()) if not (p.parent/l).exists()]; print(bad); sys.exit(bool(bad))"`. Expected: `[]`.
- [ ] **Step 4: Commit**: `docs: strategy explainers with prefer/avoid guidance, decision guide and demo questions`.

---

### Task 19: README, live smoke test and final verification

**Files:**
- Modify: `README.md`
- Create: `tests/test_live.py`

- [ ] **Step 1: Write the live smoke test.** `@pytest.mark.live`. Skip it unless `ANTHROPIC_API_KEY` is set. It:
  - ingests the sample corpus with `FastEmbedEmbedder`;
  - runs `run_question` with the real `AnthropicLLM` on "How long do I hold the reset button to factory-reset the thermostat?";
  - asserts that all three strategies end with `final`, and that at least one reports `contradiction_found`.
- [ ] **Step 2: Run** `uv run pytest -m live -v`. Expected: 1 passed, or skipped without a key. Record which one it was in the commit message.
- [ ] **Step 3: Update the README.**
  - Keep the existing vision text.
  - Add these sections:
    - "v1: retrieval strategy comparison" (what it is and what you can learn from it);
    - Quickstart (`uv sync`, `cp .env.example .env`, `uv run python -m uma ingest --sample`, `uv run python -m uma serve`, then open http://127.0.0.1:8000);
    - "Using your own manuals" (the `manuals/<id>/manual.yaml` format; that folder is git-ignored);
    - "Learn how it works" (links to the overview, the three explainers, `choosing-a-strategy.md`, `demo-questions.md`, and the ADR index);
    - Running tests.
- [ ] **Step 4: Run the full suite.** `uv run pytest -v`. Expected: all pass, with the live test deselected.
- [ ] **Step 5: Commit**: `docs: README quickstart and learning guide; live smoke test`.
