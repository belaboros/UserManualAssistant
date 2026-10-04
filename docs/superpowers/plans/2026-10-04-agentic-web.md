# Agentic & web Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth column, "Agentic & web", that researches the manuals, then the web, with a planner tool that ends each phase, and streams one merged answer that highlights conflicts between manual and web.

**Architecture:** A generic bounded tool loop (`run_phase`) runs a local phase (manual tools) and a web phase (Claude's server-side web search), each ended by a `finish_phase` planner tool. A final streamed merge call writes the answer from both phases' notes. Citations gain a `web` kind; both kinds share one `[n]` numbering.

**Tech Stack:** Python 3, FastAPI, SQLite, Anthropic Python SDK (`web_search_20260209` server tool), vanilla JS, pytest + pytest-asyncio, `FakeLLM`.

**Spec:** [docs/superpowers/specs/2026-10-04-agentic-web-design.md](../specs/2026-10-04-agentic-web-design.md)

## Global Constraints

- Strategy id `agentic_web`, title `Agentic & web`, last in `STRATEGY_ORDER`.
- Settings / env vars: `agent_web_local_max_tool_calls` = 8 (`AGENT_WEB_LOCAL_MAX_TOOL_CALLS`), `agent_web_max_searches` = 8 (`AGENT_WEB_MAX_SEARCHES`), `agent_web_timeout_s` = 180.0 (`AGENT_WEB_TIMEOUT_S`).
- `WEB_SEARCH_USD_PER_SEARCH = 0.01` in `uma/config.py`.
- Web search tool: `{"type": "web_search_20260209", "name": "web_search", "max_uses": max(remaining, 1)}`.
- `pause_turn`: resume by re-sending the conversation with no extra user message; at most 5 resumptions per phase; resumptions do not count against the budget.
- Fixed copy (exact strings):
  - Budget notice: `Tool budget reached. Call finish_phase now with what you have.`
  - Nudge: `Call finish_phase to end this phase.`
  - Search reminder: `Search the web at least once before finishing.`
  - Web unavailable notes: `Web search was unavailable.`
  - Conflict prefix: `> ⚠ **Conflict: the manual may be out of date.**`
- Agentic (`uma/strategies/agentic.py`) keeps its behaviour; its existing tests pass unchanged.
- No network in tests; `FakeLLM` only. Run tests with `uv run pytest`.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The model ends a phase with plain text and never calls `finish_phase`.** Expected: one nudge, then the phase closes with the text as notes and the pipeline still answers. Tests in Task 4.
2. **Web search fails on every call** (error blocks, e.g. web search disabled for the org). Expected: the column still answers from the manuals and says the web check could not be done. Test in Task 6.
3. **The model cites a URL or marker that was never retrieved** (`[web:<url>]` not in any search result, `[web:99]`, unknown `[§id]`). Expected: the marker is dropped, never a broken or invented citation. Tests in Tasks 3 and 5.
4. **An old database and old answer rows** (no `web_searches` column, citations without `kind`). Expected: the database migrates on start; old rows read as `web_searches = 0` and manual citations. Tests in Task 1; UI default in Task 8.
5. **The same page comes back from several searches.** Expected: one source number and one citation. Test in Task 3.

---

### Task 1: Data types, settings and log column

**Files:**
- Modify: `uma/config.py`, `uma/strategies/base.py`, `uma/log.py`
- Test: `tests/test_config.py`, `tests/test_base.py`, `tests/test_log.py`

**Interfaces:**
- Produces:
  - `Settings.agent_web_local_max_tool_calls: int = 8`, `Settings.agent_web_max_searches: int = 8`, `Settings.agent_web_timeout_s: float = 180.0`; `WEB_SEARCH_USD_PER_SEARCH: float = 0.01` in `uma/config.py`.
  - `Citation` gains trailing fields `kind: Literal["manual", "web"] = "manual"` and `url: str | None = None`.
  - `Metrics` gains trailing field `web_searches: int = 0`.
  - `answers` table gains `web_searches INTEGER`; `_answer_row` returns `web_searches` (0 when NULL) at top level and in `answer.metrics`.

- [ ] **Step 1: Write the failing tests**
  - `test_config.py::test_agent_web_defaults_and_env`: `load_settings({})` gives 8, 8, 180.0; `load_settings({"AGENT_WEB_LOCAL_MAX_TOOL_CALLS": "3", "AGENT_WEB_MAX_SEARCHES": "2", "AGENT_WEB_TIMEOUT_S": "60"})` gives 3, 2, 60.0.
  - `test_base.py::test_web_citation_serialises`: `answer_to_dict` of an `Answer` holding `Citation("example.com", "Page", "https://example.com/a", (), "", kind="web", url="https://example.com/a")` has `citations[0]["kind"] == "web"`, `["url"] == "https://example.com/a"`, and is `json.dumps`-able; a default `Citation` has `kind == "manual"` and `url is None`.
  - `test_log.py::test_web_searches_roundtrip`: an answer saved with `Metrics(..., web_searches=3)` reads back with `answers_for(qid)[sid]["web_searches"] == 3` and `["answer"]["metrics"]["web_searches"] == 3`; citation `kind`/`url` survive.
  - `test_log.py::test_old_database_gains_web_searches_column`: create the `answers` table with the pre-change schema (no `web_searches`) via `sqlite3`, insert a row, open `Log(path)`; the row reads back with `web_searches == 0`, and saving a new answer works.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_base.py tests/test_log.py -v`
Expected: the four new tests FAIL (missing attributes / column).

- [ ] **Step 3: Implement**
  - Add the settings and env parsing in `load_settings`, and the constant.
  - Add the `Citation` and `Metrics` fields.
  - In `Log.__init__`, after `executescript`, read `PRAGMA table_info(answers)` and run `ALTER TABLE answers ADD COLUMN web_searches INTEGER` if missing. Add the column to `_SCHEMA`, to the INSERT in `save_answer`, and to `_answer_row`.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add uma/config.py uma/strategies/base.py uma/log.py tests/test_config.py tests/test_base.py tests/test_log.py
git commit -m "feat: add web citation kind, web_searches metric and agentic-web settings"
```

---

### Task 2: Extract the manual tools from Agentic

**Files:**
- Create: `uma/strategies/manual_tools.py`
- Modify: `uma/strategies/agentic.py`
- Test: `tests/test_agentic.py` (unchanged, must pass), `tests/test_manual_tools.py`

**Interfaces:**
- Produces, in `uma/strategies/manual_tools.py`:
  - `MANUAL_TOOLS: list[dict]`: the three tool definitions now in `agentic.TOOLS`, unchanged.
  - `class ToolError(Exception)`.
  - `class ManualTools: __init__(self, store: CorpusStore, embedder: Embedder)`; `run(self, name: str, tool_input: object) -> str` (raises `ToolError`); `lookup(self, section_id: str) -> Citation | None`.
- `agentic.py` keeps exporting `TOOLS` (`TOOLS = MANUAL_TOOLS`) because `tests/test_agentic.py` imports it.

- [ ] **Step 1: Write `tests/test_manual_tools.py::test_run_and_lookup`**: with `sample_store` and `embedder`, `ManualTools(...).run("read_section", {"section_id": PAIRING})` ends with the section text; `run("nope", {})` raises `ToolError`; `lookup(PAIRING).section_id == PAIRING`; `lookup("missing") is None`.
- [ ] **Step 2: Run it; expect FAIL (module not found).** `uv run pytest tests/test_manual_tools.py -v`
- [ ] **Step 3: Move `_run_tool`, `_lookup`, `_titles` and `_ToolError` into `ManualTools`; make `AgenticStrategy` hold a `ManualTools` and call it.** Behaviour and tool output text stay byte-identical.
- [ ] **Step 4: Run** `uv run pytest tests/test_manual_tools.py tests/test_agentic.py -v`. Expected: all PASS, with no edit to `test_agentic.py`.
- [ ] **Step 5: Commit** — `refactor(agentic): extract manual tools into a shared module`

---

### Task 3: Web sources and mixed citation markers

**Files:**
- Create: `uma/strategies/web_sources.py`
- Modify: `uma/strategies/base.py`
- Test: `tests/test_web_sources.py`, `tests/test_base.py`

**Interfaces:**
- Produces, in `uma/strategies/web_sources.py`:
  - `class WebSources`: `add(url: str, title: str) -> int` (1-based; returns the existing number for a known URL); `number(url: str) -> int | None`; `citation(n: int) -> Citation | None` (web citation per spec 3.2: `manual_id` = URL host, `manual_title` = title, `section_id` = URL, `heading_path=()`, `cited_text=""`, `kind="web"`, `url` = URL); `listing() -> str` (one line per source: `[web:<n>] <title> — <url>`); `rewrite(notes: str) -> str` (turns `[web:<url>]` into `[web:<n>]`, removes markers whose URL is unknown); `__len__`.
- Produces, in `base.py`: `resolve_mixed_markers(text: str, lookup: Callable[[str], Citation | None], sources: WebSources) -> tuple[str, list[Citation]]`. One left-to-right pass over `[§<id>]` and `[web:<n>]`, sharing `_index_of` numbering; unknown markers are removed.

- [ ] **Step 1: Write the failing tests**
  - `test_web_sources.py::test_add_dedupes_by_url`: adding `a`, `b`, `a` gives 1, 2, 1 and `len == 2`.
  - `test_web_sources.py::test_rewrite_maps_and_drops`: with `https://a.example/x` added, `rewrite("X [web:https://a.example/x]. Y [web:https://never.example/].")` returns `"X [web:1]. Y ."`.
  - `test_web_sources.py::test_citation_fields`: `citation(1)` has `kind == "web"`, `url`, `manual_id == "a.example"`; `citation(9) is None`.
  - `test_base.py::test_resolve_mixed_markers_shares_numbering`: text `"A [§s1]. B [web:1]. C [§s1]. D [web:9]. E [§zz]."` with lookup knowing only `s1` gives `"A [1]. B [2]. C [1]. D . E ."` and citations `[s1 manual, web 1]`.
- [ ] **Step 2: Run; expect FAIL.** `uv run pytest tests/test_web_sources.py tests/test_base.py -v`
- [ ] **Step 3: Implement both.** Use one regex `\[(?:§([^\]]+)|web:(\d+))\]` for the mixed resolver.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** — `feat(strategies): number web sources and resolve mixed manual/web markers`

---

### Task 4: `run_phase`: the bounded loop with the planner tool

**Files:**
- Create: `uma/strategies/phase.py`
- Modify: `uma/llm.py` (FakeLLM helpers)
- Test: `tests/test_phase.py`

**Interfaces:**
- Consumes: `ToolError` (Task 2); `WebSources` (Task 3); `LLM`, `Usage`, `LLMResponse`.
- Produces, in `uma/strategies/phase.py`:
  - `FINISH_PHASE_TOOL: dict`: exactly the JSON in spec 2.3.
  - `@dataclass class PhaseResult: sufficient: bool; gaps: list[str]; notes: str; usage: Usage; tool_calls: int; web_searches: int; forced: bool`.
  - `async def run_phase(llm: LLM, *, phase: Literal["local", "web"], system: str, prompt: str, tools: list[dict], run_tool: Callable[[str, object], str] | None, budget: int, sources: WebSources | None = None) -> AsyncIterator[TraceStep | PhaseResult | Failed]`. It yields trace steps, then exactly one `PhaseResult` or `Failed` as its last item. `tools` excludes `FINISH_PHASE_TOOL`, which `run_phase` appends. Client tools run via `asyncio.to_thread(run_tool, ...)`.
- Produces, in `uma/llm.py`: `finish_phase_response(sufficient: bool, gaps: list[str], notes: str, *, extra: list[dict] | None = None) -> LLMResponse` (a `tool_use` turn; `extra` blocks go before the `finish_phase` block).

Behaviour this task pins (local phase; web specifics are Task 5):
- `finish_phase` ends the phase; other `tool_use` blocks in that turn run first, and their trace steps come first.
- `finish_phase` does not count against `budget`. Client calls beyond `budget` get an `is_error` result `Tool budget exhausted.`. When the count reaches `budget`, the budget notice text is appended to that turn's user message.
- After the budget notice, one more turn: if it calls `finish_phase`, the result has `forced=True`. Otherwise the result is `sufficient=False`, `gaps=["budget exhausted"]`, `notes` = that turn's text, `forced=True`.
- A turn with no tool call gets the nudge as a user message once. A second such turn closes the phase as above, with `gaps=["did not call finish_phase"]`.
- Trace kinds: `tool_call` `{phase, name, input, summary}`; `planner` `{phase, sufficient, gaps, forced}`.
- `stop_reason` `refusal` / `max_tokens` and `LLMError` produce `Failed` with Agentic's messages.

- [ ] **Step 1: Write the failing tests in `tests/test_phase.py`** (a `FakeLLM` and a stub `run_tool` that records calls):
  - `test_finish_phase_ends_phase`: `[tool_use search, finish_phase_response(True, [], "N [§s1]")]` gives trace kinds `["tool_call", "planner"]` and a result with `sufficient=True`, `notes == "N [§s1]"`, `tool_calls == 1`, `forced is False`; the first request's tools end with `FINISH_PHASE_TOOL`.
  - `test_other_tools_run_before_finish`: one response with `extra=[search tool_use]` plus `finish_phase` runs the search (stub called once) and then ends.
  - `test_budget_forces_close_with_finish`: `budget=2`, three single-search turns then `finish_phase`; the third search gets `is_error` with `Tool budget exhausted.`, the budget notice is in the third request's last user message, and the result has `forced is True`.
  - `test_budget_forces_close_without_finish`: as above, but the last turn is `text_response("partial")`; the result has `notes == "partial"`, `gaps == ["budget exhausted"]`, `sufficient is False`.
  - `test_plain_text_gets_one_nudge_then_closes` *(Review Focus 1)*: `[text_response("a"), text_response("b")]`; the second request's last user message is the nudge; the result has `notes == "b"`, `gaps == ["did not call finish_phase"]`.
  - `test_refusal_and_llm_error_fail`: a refusal response gives a `Failed` as the last item; a FakeLLM that raises `LLMError("x")` gives `Failed("x")`.
- [ ] **Step 2: Run; expect FAIL.** `uv run pytest tests/test_phase.py -v`
- [ ] **Step 3: Implement `run_phase` and `finish_phase_response`.** Echo assistant content unchanged; send all tool results of a turn in one user message (same as `agentic.py`).
- [ ] **Step 4: Run** `uv run pytest tests/test_phase.py tests/test_agentic.py -v`; expect PASS.
- [ ] **Step 5: Commit** — `feat(strategies): bounded phase loop ended by a finish_phase planner tool`

---

### Task 5: Web phase in `run_phase`: server search, `pause_turn`, at least one search

**Files:**
- Modify: `uma/strategies/phase.py`, `uma/llm.py`
- Test: `tests/test_phase.py`

**Interfaces:**
- Produces, in `uma/strategies/phase.py`: `web_search_tool(max_uses: int) -> dict` returning the Global Constraints shape.
- Produces, in `uma/llm.py`: `web_search_blocks(query: str, results: list[tuple[str, str]] | None, *, error_code: str | None = None, id: str | None = None) -> list[dict]`, returning a `server_tool_use` block (`name="web_search"`, `input={"query": ...}`) and a matching `web_search_tool_result` block whose `content` is a list of `{"type": "web_search_result", "url", "title"}` or, on error, `{"type": "web_search_tool_result_error", "error_code": ...}`; and `pause_turn_response(blocks: list[dict]) -> LLMResponse`.

Behaviour this task pins, when `phase == "web"`:
- Each request's `tools` holds `web_search_tool(max(budget - web_searches, 1))` and `FINISH_PHASE_TOOL`; `run_tool` is `None`, so any other `tool_use` gets an `is_error` result `Unknown tool: <name>`.
- Each `server_tool_use` named `web_search` counts as one search. Its paired result yields a trace `web_search` `{phase: "web", query, result_count}`, or `{phase: "web", query, error_code}`. Successful results are added to `sources`.
- Reaching `budget` searches triggers the same budget notice and force-close as Task 4.
- `finish_phase` with `web_searches == 0` gets an `is_error` result with the search reminder and does not end the phase. The nudge in the web phase starts with the search reminder when no search has run.
- `pause_turn`: append the assistant content and call again with no new user message; after 5 resumptions, close as in the budget case.
- When the phase ends, `notes` are passed through `sources.rewrite`. If every search failed, `notes` is `Web search was unavailable.` and `sufficient=False`.

- [ ] **Step 1: Write the failing tests:**
  - `test_web_search_counted_traced_and_sourced`: one response with `web_search_blocks("q", [("https://a.example/x", "A")])` then `finish_phase` notes `"Y [web:https://a.example/x] Z [web:https://b.example/]"`; result `web_searches == 1`, `notes == "Y [web:1] Z "`, and a trace `web_search` with `result_count == 1`; the first request's web tool has `max_uses == budget`.
  - `test_duplicate_urls_one_source` *(Review Focus 5)*: two searches both returning `https://a.example/x` leave `len(sources) == 1`.
  - `test_finish_without_search_is_rejected`: `finish_phase` first gets the search reminder as an `is_error` result; then a search and `finish_phase` ends normally.
  - `test_pause_turn_resumed_without_user_message`: `[pause_turn_response(search blocks), finish_phase]`; the second request's last message is the assistant turn (role `assistant`), and `web_searches == 1`.
  - `test_six_pauses_force_close`: six `pause_turn_response`s and then a text turn end the phase with `forced=True`.
  - `test_all_searches_error` *(part of Review Focus 2)*: one search with `error_code="unavailable"` and then `finish_phase`; result `notes == "Web search was unavailable."`, `sufficient is False`; trace carries `error_code`.
  - `test_max_uses_tracks_remaining_budget`: `budget=2`, after one search the next request's web tool has `max_uses == 1`; after two, still `1`.
- [ ] **Step 2: Run; expect FAIL.** `uv run pytest tests/test_phase.py -v`
- [ ] **Step 3: Implement.** Treat an error result as one whose `content` is a dict, and a success as one whose `content` is a list.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** — `feat(strategies): web phase with server-side search, pause_turn and source tracking`

---

### Task 6: `AgenticWebStrategy`, its rules and the merge

**Files:**
- Create: `uma/strategies/agentic_web.py`
- Modify: `uma/strategies/rules.py`, `uma/runner.py`
- Test: `tests/test_agentic_web.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `ManualTools`, `MANUAL_TOOLS` (Task 2); `WebSources`, `resolve_mixed_markers` (Task 3); `run_phase`, `PhaseResult`, `web_search_tool` (Tasks 4–5); settings and `WEB_SEARCH_USD_PER_SEARCH` (Task 1).
- Produces:
  - `rules.py`: `AGENTIC_WEB_LOCAL`, `AGENTIC_WEB_SEARCH`, `AGENTIC_WEB_MERGE_RULES` (the merge rules are the bullet list in spec 2.6 plus the status tag lines from `ANSWERING_RULES`; the conflict line quotes the exact conflict prefix).
  - `class AgenticWebStrategy: id = "agentic_web"; title = "Agentic & web"; timeout_s: float` (from `settings.agent_web_timeout_s`); `__init__(self, store, embedder, llm, settings)`; `answer(question) -> AsyncIterator[AnswerEvent]`.
  - `runner._run_one` uses `getattr(strategy, "timeout_s", None) or timeout_s`.

Behaviour:
- The local phase prompt is the question. The web phase prompt is the question plus the local `notes` and `gaps` (spec 2.2). The merge user message contains the question, both phases' notes and gaps, and `sources.listing()`.
- The merge streams `TextDelta`s through `StatusTagFilter`; markers are resolved with `resolve_mixed_markers`. If the text contains the conflict prefix, the status is `contradiction_found`.
- `Metrics`: `usage` summed over all phases and the merge; `tool_calls` = local client calls; `web_searches` from the web phase; `cost_usd` = token cost + `web_searches * WEB_SEARCH_USD_PER_SEARCH` (None if the model has no price); `manuals_used` = titles of `kind == "manual"` citations only.
- A `Failed` from either phase is yielded and ends the strategy.

- [ ] **Step 1: Write the failing tests in `tests/test_agentic_web.py`** (`sample_store`, `embedder`, `PAIRING`):
  - `test_three_phases_then_mixed_citations`: local `read_section` + `finish_phase` (notes cite `[§PAIRING]`), web search on `https://a.example/x` + `finish_phase` citing it, merge text `"Hold Link [§PAIRING]. Newer firmware [web:1].\n<status>answered</status>"`. The final text is `"Hold Link [1]. Newer firmware [2]."`, the citations' kinds are `["manual", "web"]`, `web_searches == 1`, `tool_calls == 1`, and `manuals_used` lists one manual title. Trace phases appear in the order local, web. The merge request has `tools is None` and its user message contains `[web:1]` and the source listing. `<status>` is never streamed.
  - `test_cost_includes_searches`: with `Settings()` model prices, `cost_usd` equals `cost_usd(model, ...)` of the summed usage plus `0.01 * web_searches`.
  - `test_conflict_block_sets_contradiction`: merge text starting with the conflict prefix and tagged `answered` gives status `contradiction_found`.
  - `test_web_unavailable_still_answers` *(Review Focus 2)*: the web search returns `error_code="unavailable"`; the merge request contains `Web search was unavailable.`; the strategy yields `Final`.
  - `test_phase_failure_is_failed`: the local phase gets a refusal, so the last event is `Failed` and no merge call is made.
  - `test_runner.py::test_runner_uses_strategy_timeout`: a slow stub strategy with `timeout_s = 0.05`, run with global `timeout_s=10`, is reported as `Timed out after 0.05 s`.
- [ ] **Step 2: Run; expect FAIL.** `uv run pytest tests/test_agentic_web.py tests/test_runner.py -v`
- [ ] **Step 3: Implement the rules, the strategy and the runner change.**
- [ ] **Step 4: Run** `uv run pytest`; expect all PASS.
- [ ] **Step 5: Commit** — `feat(strategies): add the Agentic & web strategy`

---

### Task 7: Register the strategy in the web app

**Files:**
- Modify: `uma/web.py`, `tests/test_web.py`, `tests/test_docs.py` (`test_every_api_diagram_exists` count only)

**Interfaces:**
- Consumes: `AgenticWebStrategy` (Task 6).
- Produces: `STRATEGY_ORDER == ["baseline", "whole_context", "rag", "agentic", "agentic_web"]`; `_DOCS["agentic_web"] == "/docs/strategies/4-agentic-web.md"`.

With plain-text `FakeLLM` responses, `agentic_web` makes 5 calls (local phase 2 and web phase 2, because each phase gets one nudge, then merge 1). The other strategies make 1 each.

- [ ] **Step 1: Update the tests first:**
  - `test_strategy_order_starts_with_baseline`: expect the five ids.
  - `make_client` and the `BlockingLLM` test: script `len(STRATEGY_ORDER) + 4` responses.
  - `test_partial_answers_run_only_missing_strategies`: `len(llm.calls) == 8` (3 single-call strategies + 5).
  - `test_strategies_status_and_static`: add `s[4]["doc"] == "/docs/strategies/4-agentic-web.md"`.
  - `test_every_api_diagram_exists`: `len(strategies) == 5`.
- [ ] **Step 2: Run** `uv run pytest tests/test_web.py -v`; expect FAIL on order and count.
- [ ] **Step 3: Register `AgenticWebStrategy` in `create_app`, and update `STRATEGY_ORDER` and `_DOCS`.**
- [ ] **Step 4: Run** `uv run pytest tests/test_web.py -v`; expect PASS. (`test_every_api_diagram_exists` stays red until Task 9 adds the diagrams.)
- [ ] **Step 5: Commit** — `feat(web): serve the Agentic & web strategy as the fifth column`

---

### Task 8: Frontend: fifth column, web citations, conflict styling

**Files:**
- Modify: `uma/static/index.html`, `uma/static/app.js`, `uma/static/style.css`
- Test: `tests/test_static.py`

Behaviour:
- A fifth `<section class="column" data-strategy="agentic_web">` copied from the Agentic section, with ids `title-agentic_web` and `badge-agentic_web`, and title text `Agentic & web` (written `Agentic &amp; web` in HTML).
- Grid: `repeat(5, minmax(0, 1fr))` at `min-width: 1200px`.
- Fix the `blindLabel` comment: five columns are V/W/X/Y/Z. The function itself already generalises.
- `linkCitations`: when `cit.kind === "web"`, render an `<a href={cit.url} target="_blank" rel="noopener noreferrer">[n]</a>` with `title` = page title. Otherwise keep the section-panel button. A missing `kind` means manual *(Review Focus 4)*.
- `formatMetrics`: when `m.web_searches` > 0, add `· <n> web searches`. The footer shows `Manuals: …` and `Web: <unique hosts of web citations>`.
- The trace renders the new kinds: `planner` as `<phase> planner: sufficient|insufficient (gaps: …)`, and `web_search` as `web search: "<query>" → <n> results` or `→ error <code>`.
- Conflict styling: after Markdown rendering, a `blockquote` whose text starts with `⚠ Conflict` gets class `conflict` (warning border and background tokens in both themes).

- [ ] **Step 1: Add `'data-strategy="agentic_web"'` to `REQUIRED` in `tests/test_static.py`, and add `test_web_citation_markup_is_safe`, which asserts that `app.js` contains `rel = "noopener noreferrer"` (or the attribute string you use) and `"_blank"`.**
- [ ] **Step 2: Run** `uv run pytest tests/test_static.py -v`; expect FAIL.
- [ ] **Step 3: Implement the HTML, CSS and JS changes above.**
- [ ] **Step 4: Run** `uv run pytest tests/test_static.py -v`; expect PASS. Then start the app (`uv run python -m uma serve`) and check by hand: five columns at ≥1200 px; maximize/restore and blind mode work with five; a web citation opens a new tab; a manual citation opens the side panel.
- [ ] **Step 5: Commit** — `feat(ui): fifth column with web citations and conflict highlighting`

---

### Task 9: Documentation, diagrams and ADR

**Files:**
- Create: `docs/strategies/4-agentic-web.md`, `uma/static/diagrams/agentic_web-flow.mmd`, `uma/static/diagrams/agentic_web-sequence.mmd`, `docs/adr/0014-agentic-web-strategy.md`
- Modify: `docs/choosing-a-strategy.md`, `docs/demo-questions.md`, `docs/architecture/overview.md`, `uma/static/diagrams/overview.mmd`, `docs/adr/README.md`, `README.md`, `tests/test_docs.py`

Content:
- The strategy page uses the eight fixed headings (`EXPLAINER_HEADINGS`) in order and embeds both diagrams verbatim. "Cost and latency" has a worked example: say 8 local calls, 3 searches and a merge on Sonnet 5.5, priced with `PRICES` plus $0.01 per search. "Avoid when" names: answers must come only from approved content; cost or latency is tight; the network or web search is unavailable or not allowed.
- The flow diagram shows local phase → planner → web phase → planner → merge, with the budget and force-close branches. The sequence diagram shows the participants App, Claude, Corpus and Web search, with a `pause_turn` note.
- ADR 0014 follows the existing ADR format. Decision: one strategy may use web search, as a deliberate exception to ADR 0006; server-side `web_search_20260209` rather than a third-party search API (no extra key, built-in citations, $10 per 1,000 searches). Consequences include the empty-corpus behaviour and the "manual may be out of date" use.
- `choosing-a-strategy.md`: an "Agentic & web" column in every matrix row, a flowchart branch ("Must answers be checked against the live web?"), and a sentence in "Mixing strategies" pointing to it. Update "three retrieval strategies" wording where it now reads wrong.
- `demo-questions.md`: two or three conflict-detection questions against the sample manuals, each with what to look for.
- `overview.md` links ADR 0014 and mentions the fifth strategy; `overview.mmd` shows it; `README.md` lists it.

- [ ] **Step 1: Add `("agentic_web", "4-agentic-web.md")` to `STRATEGY_DOCS` in `tests/test_docs.py`.**
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -v`; expect FAIL (missing files).
- [ ] **Step 3: Write the docs and diagrams above.**
- [ ] **Step 4: Run** `uv run pytest`; expect the whole suite to PASS.
- [ ] **Step 5: Commit** — `docs: explain the Agentic & web strategy (page, diagrams, ADR 0014, matrix)`
