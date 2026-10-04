# Agentic & web strategy: Design

- **Date:** 2026-10-04
- **Status:** Draft, awaiting review
- **Builds on:** [Strategy comparison design](2026-10-04-strategy-comparison-design.md)
- **Decisions:** ADR 0014 (to be written with the implementation)

## 1. Purpose

Add a fifth column, **"Agentic & web"**, to the right of Agentic. It answers a question from the
local manuals **and** from a web search, then writes one merged answer. It is an improved Agentic:
it adds explicit planning steps that decide when each phase has done enough, and a separate merge
step.

Its main teaching point is **conflict detection**. When the web disagrees with a manual, the answer
highlights the conflict, cites both the manual section and the web page, and says that the manual
may need updating. That makes the column useful for keeping local manuals up to date, not only for
answering questions.

Success means:

1. Every answer comes from both phases. The web phase always runs, even when the manuals seem
   complete, because an outdated manual can only be caught by checking it.
2. Every claim is cited, and the reader can tell manual sources from web sources.
3. Conflicts between manual and web are never silently resolved. Both versions are shown, both are
   cited, and the status is `contradiction_found`.
4. The stop decision of each phase is visible in the trace, with its reason.
5. The strategy is documented like the others: a strategy page, flow and sequence diagrams, a
   column in the decision matrix, and an ADR.

### Out of scope

- Changing the existing Agentic strategy. It stays as it is. Moving it onto the shared phase loop
  is a possible later refactor.
- Writing web findings back into the manuals. The column only points out what may need updating.
- Fetching full web pages (`web_fetch`). Search results are enough for this version.
- A new status tag. Conflicts reuse `contradiction_found`.

## 2. Behaviour

The strategy runs three phases in order. Each phase is its own LLM conversation, orchestrated in
Python.

### 2.1 Local phase

- Tools: `list_manuals`, `search`, `read_section` (the same tools and behaviour as Agentic), plus
  the planner tool `finish_phase`.
- Budget: `AGENT_WEB_LOCAL_MAX_TOOL_CALLS`, default 8. `finish_phase` does not count against it.
- The phase ends when the model calls `finish_phase`.

### 2.2 Web phase

- Tools: the server-side `web_search_20260209` tool with `max_uses` set to the budget, plus
  `finish_phase`.
- Budget: `AGENT_WEB_MAX_SEARCHES`, default 8.
- Input: the question, plus the local phase's `notes` and `gaps`. The prompt asks the model to
  fill the gaps **and** to check the claims the manuals make, especially versions, dates, settings
  and procedures that may have changed.
- At least one search is required. If the model calls `finish_phase` before searching, the tool
  result is an error ("Search the web at least once before finishing") and the loop continues.
- `stop_reason: "pause_turn"` is resumed by re-sending the conversation unchanged (no extra user
  message). Resumptions do not count against the budget. At most 5 resumptions per phase; after
  that the phase is force-closed (2.4).

### 2.3 The `finish_phase` planner tool

```json
{
  "name": "finish_phase",
  "description": "Call when this phase has gathered enough, or cannot gather more. Ends the phase.",
  "strict": true,
  "input_schema": {
    "type": "object",
    "properties": {
      "sufficient": {"type": "boolean"},
      "gaps": {"type": "array", "items": {"type": "string"}},
      "notes": {"type": "string"}
    },
    "required": ["sufficient", "gaps", "notes"],
    "additionalProperties": false
  }
}
```

- `sufficient`: whether this phase's sources answer the question on their own.
- `gaps`: what is still unknown after this phase.
- `notes`: the findings, with citation markers: `[§<section_id>]` in the local phase, and
  `[web:<url>]` in the web phase, using the URL of a search result the phase received (2.5).

If `finish_phase` comes in the same turn as other tool calls, those calls run first and then the
phase ends.

### 2.4 Force-close on budget

When a phase uses up its budget without calling `finish_phase`, the tool results for that turn
are followed by the text "Tool budget reached. Call finish_phase now with what you have." The
model gets one more turn. If it still does not call `finish_phase`, the phase ends with
`sufficient=false`, `gaps=["budget exhausted"]`, and its last text as `notes`. The pipeline goes
on to the next phase either way.

### 2.5 Web sources

Each `web_search_result` the web phase receives is added to a numbered source list (URL, title),
with duplicates removed by URL. The model cites web sources in its `finish_phase` notes as
`[web:<url>]`, because the URLs are already in its context and need no extra bookkeeping. When the
phase ends, the strategy rewrites each `[web:<url>]` to `[web:<n>]`, using the source list. A URL
that is not in the list (one the model did not receive from a search) is dropped together with its
marker, so the answer can only cite pages that were actually retrieved.

### 2.6 Merge phase

- One streamed call with no tools. This is the only phase that streams answer text.
- Input: the question, the local notes and gaps, the web notes and gaps (with `[web:<n>]` markers),
  and the numbered web source list.
- Rules (they replace `ANSWERING_RULES` for this strategy; ADR 0014):
  - Answer from the manuals first. Use the web to fill gaps and to check the manuals.
  - Cite every claim, with `[§<section_id>]` for manual content and `[web:<n>]` for web content.
  - When manual and web disagree, write a conflict block (2.7). Do not pick a winner.
  - If neither source answers the question, say so plainly.
  - The same status tag protocol as every strategy (ADR 0009): `answered`, `not_covered`, or
    `contradiction_found` when there is at least one conflict.
- Markers are resolved into one shared `[n]` sequence covering both kinds of citation.

### 2.7 Conflict block

The merge writes each conflict as a Markdown block quote that starts with a fixed prefix:

```markdown
> ⚠ **Conflict: the manual may be out of date.** The manual says X [1]. The web says Y [2].
```

The UI recognises the `⚠ **Conflict` prefix and styles the block so it stands out.

## 3. Architecture

### 3.1 New and changed modules

| Module | Change |
|---|---|
| `uma/strategies/manual_tools.py` (new) | The local tool definitions and their implementation, extracted from `agentic.py`. Agentic imports them from here; its behaviour does not change. |
| `uma/strategies/phase.py` (new) | `run_phase(...)`: a bounded tool loop that ends on `finish_phase` or force-close, yields `TraceStep`s, and returns a `PhaseResult(sufficient, gaps, notes, usage, tool_calls, web_searches)`. It handles server-tool blocks and `pause_turn`. |
| `uma/strategies/agentic_web.py` (new) | `AgenticWebStrategy`: `id = "agentic_web"`, `title = "Agentic & web"`, `timeout_s = 180`. Runs local phase, web phase, merge. |
| `uma/strategies/rules.py` | Adds `AGENTIC_WEB_LOCAL`, `AGENTIC_WEB_SEARCH` and `AGENTIC_WEB_MERGE_RULES`. |
| `uma/strategies/base.py` | `Citation` gains `kind: Literal["manual", "web"] = "manual"` and `url: str \| None = None`. `Metrics` gains `web_searches: int = 0`. Adds `resolve_mixed_markers(text, lookup_section, web_sources)`. |
| `uma/config.py` | Settings `agent_web_local_max_tool_calls` (8), `agent_web_max_searches` (8), `agent_web_timeout_s` (180.0), from env vars `AGENT_WEB_LOCAL_MAX_TOOL_CALLS`, `AGENT_WEB_MAX_SEARCHES`, `AGENT_WEB_TIMEOUT_S`. `WEB_SEARCH_USD_PER_SEARCH = 0.01`. |
| `uma/llm.py` | `FakeLLM` helpers for scripting `server_tool_use`, `web_search_tool_result` and `pause_turn` responses. `AnthropicLLM` needs no change, because it already passes `tools` through. |
| `uma/runner.py` | Uses a strategy's `timeout_s` attribute when it has one, otherwise the global `strategy_timeout_s`. |
| `uma/log.py` | Adds a `web_searches INTEGER` column to `answers`, added with `ALTER TABLE` when an existing database lacks it. |
| `uma/web.py` | Registers the strategy and appends `"agentic_web"` to `STRATEGY_ORDER`. Adds its doc path. |
| `uma/static/*` | Fifth column, 5-column grid at ≥1200px, blind labels V–Z, web citations open the URL in a new tab, footer splits manual and web sources, conflict block styling. |

### 3.2 Citations for web sources

A web `Citation` has `kind="web"`, `url` set to the page URL, `manual_title` set to the page title,
`section_id` set to the URL, `heading_path` empty, and `manual_id` set to the URL's host. Existing
code that reads `manual_title` or `section_id` keeps working. `manuals_used` in `Metrics` lists
manual titles only.

### 3.3 Cost

`cost_usd` = token cost across all three phases + `web_searches × $0.01`. The strategy page gives a
worked example.

### 3.4 Trace steps

| Step kind | Detail |
|---|---|
| `tool_call` | `{phase: "local", name, input, summary}`, as in Agentic plus `phase` |
| `web_search` | `{phase: "web", query, result_count}` or `{..., error_code}` |
| `planner` | `{phase, sufficient, gaps, forced: bool}` |

## 4. Error handling

| Situation | Behaviour |
|---|---|
| Local phase budget used without `finish_phase` | Force-close (2.4) and continue. |
| Web phase budget used without `finish_phase` | Force-close (2.4) and continue. `max_uses` is the server-side backstop. |
| Web search returns an error block | Not an exception. Recorded as a `web_search` trace step with `error_code`. If no search has succeeded, the web phase ends with `notes="Web search was unavailable."` and the merge says the web check could not be done. The column still answers. |
| Empty corpus | The local phase finds nothing; the web phase runs; the merge answers from the web and labels it as such. Documented as a difference from the other columns. |
| `refusal`, `max_tokens`, `LLMError` in any phase | `Failed`, with the same messages as Agentic. |
| Overall time limit | 180 s by default, enforced by the runner. |
| Missing or malformed status tag | `answered` plus a logged warning, as in every strategy. |

## 5. Testing

TDD with `FakeLLM`; no network.

- `run_phase`: stops on `finish_phase`; runs other tool calls in the same turn first; force-closes
  on budget, both when the model then calls `finish_phase` and when it does not; emits `planner`
  trace steps.
- Web phase: resumes `pause_turn` without counting it; enforces at least one search; handles
  error blocks; numbers and deduplicates sources; rewrites `[web:<url>]` to `[web:<n>]` and drops
  URLs that no search returned.
- Merge: resolves mixed `[§id]` and `[web:n]` markers into one `[n]` sequence; drops unknown
  markers; a conflict answer gets `contradiction_found`.
- `Citation` and `Metrics` additions round-trip through the log; an old database gains the
  `web_searches` column.
- Runner: a strategy's own `timeout_s` is used.
- Web app: `/api/strategies` lists five strategies in order; replay keeps that order.
- Agentic's existing tests pass unchanged after the tool extraction.

## 6. Documentation

- `docs/strategies/4-agentic-web.md`: how it works, the phases and planners, conflict detection,
  cost and latency with a worked example, when to prefer it and when to avoid it.
- `uma/static/diagrams/agentic_web-flow.mmd` and `agentic_web-sequence.mmd`.
- `docs/choosing-a-strategy.md`: a fifth column in the decision matrix, a branch in the flowchart,
  and a link from "Mixing strategies".
- `docs/adr/0014-agentic-web-strategy.md`: web search in one strategy as a deliberate exception to
  ADR 0006, and the choice of Claude's server-side web search over a third-party search API.
- `docs/demo-questions.md`: two or three questions that show conflict detection, for example one
  about a setting or firmware version that has changed since the manual was written.
- `docs/architecture/overview.md` and `README.md`: mention the fifth strategy.
