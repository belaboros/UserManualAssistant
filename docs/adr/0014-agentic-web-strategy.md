# ADR 0014: An "Agentic & web" strategy that checks the manuals against the web

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Every strategy so far answers only from the manuals (ADR 0006), or, for the baseline, from the
model's own knowledge (ADR 0013). None of them can tell that a manual is out of date. Firmware,
apps and procedures change faster than documentation, and a manual that confidently describes last
year's menu is a common source of wrong answers. The README's goal of reporting gaps and
inconsistencies to manual authors needs a source of truth outside the manuals to compare them with.

A fifth column, **Agentic & web**, adds that source. It researches the manuals with the same tools
as Agentic, then searches the web to fill gaps and to check the manuals' claims, and merges both
into one answer that cites each source and highlights conflicts. Two decisions follow: whether one
strategy may break ADR 0006's rule of "same rules, manuals only", and which web search to use.

## Options considered

**Scope**

1. **A separate strategy that may use the web, as a deliberate exception to ADR 0006**
   - **Pros:**
     - The other four columns stay a controlled, manuals-only comparison.
     - Side by side with Agentic, it shows exactly what the web adds, and what it costs.
     - Conflict detection becomes visible and testable (`contradiction_found` plus a conflict block).
   - **Cons:**
     - Its answers are not comparable on equal terms: it has more sources, its own rules and a longer timeout.
     - Answers no longer come only from approved content.
2. **Add web search to every strategy**
   - **Pros:** Every column could flag outdated manuals.
   - **Cons:** Destroys the comparison of retrieval mechanisms that the demo exists for, and multiplies cost and latency.
3. **No web search**
   - **Pros:** Keeps the demo simple, offline-capable and cheap.
   - **Cons:** Outdated manuals stay invisible, and the README's "report inconsistencies" goal has nothing to compare against.

**Web search provider**

1. **Claude's server-side web search tool (`web_search_20260209`)**
   - **Pros:**
     - No extra API key, account or client code: Anthropic runs the searches inside the Messages API call.
     - Results come back as structured blocks with URLs and titles, which the app numbers and turns into citations.
     - Priced per search ($10 per 1,000 searches, $0.01 each), and `max_uses` caps the searches per request.
   - **Cons:**
     - Long turns can stop with `pause_turn` and must be resumed.
     - Search queries and results are sent through Anthropic; an organisation can turn the tool off.
     - Less control over the search engine, ranking and result size.
2. **A third-party search API (for example a search engine's REST API) called as a client tool**
   - **Pros:** Full control over the engine, filters and result format; can be swapped.
   - **Cons:** Another key and account to manage, more client code, no built-in citation metadata, and its own pricing to explain.
3. **Fetch known vendor pages directly**
   - **Pros:** Precise when you know where the authoritative page is.
   - **Cons:** Needs a curated URL list per product; doesn't generalise to "check this claim".

## Decision

Use scope option 1 and provider option 1:
- `AgenticWebStrategy` in `uma/strategies/agentic_web.py` (id `agentic_web`, title "Agentic & web") runs three phases in Python: a local phase with the manual tools, a web phase with Claude's server-side `web_search_20260209` tool, and a streamed merge call without tools. A planner tool, `finish_phase(sufficient, gaps, notes)`, ends each tool phase.
- Budgets: 8 local tool calls (`AGENT_WEB_LOCAL_MAX_TOOL_CALLS`) and 8 searches (`AGENT_WEB_MAX_SEARCHES`). The web phase always searches at least once, because an outdated manual can only be caught by checking it.
- The strategy uses the same model and effort as the others, but its own prompts (`AGENTIC_WEB_LOCAL`, `AGENTIC_WEB_SEARCH`, `AGENTIC_WEB_MERGE_RULES`), which replace the shared `ANSWERING_RULES`, and its own timeout of 180 seconds (`AGENT_WEB_TIMEOUT_S`).
- Web pages are cited with `[web:<url>]` in the web phase's notes; URLs that no search returned are dropped. Manual and web citations share one `[n]` numbering; web citations have `kind: "web"` and a URL (extending ADR 0012).
- Disagreements are written as a block quote starting with `⚠ **Conflict: the manual may be out of date.**`, citing both sides, with the status `contradiction_found` (ADR 0009); the strategy forces that status if the model forgets it.
- Cost is the token cost of all three phases plus $0.01 per search (`WEB_SEARCH_USD_PER_SEARCH`), and the number of searches is stored as a `web_searches` metric.

## Consequences

- ADR 0006 still holds for the other four columns. This column is the one named exception, and its explainer says so; differences between it and Agentic come from the web phase and the planner and merge steps, not from retrieval alone.
- It is the slowest and most expensive column: about four times Agentic's cost in the worked example, and 40–70 seconds instead of 15–30.
- Conflict blocks make the column useful for documentation upkeep: a `contradiction_found` answer points at a manual section that may need updating. False conflicts are possible when web results are about another product or are wrong, so a human checks before editing a manual.
- If the searches fail, the column still answers from the manuals and says the web check could not be done. If the manuals have nothing on the question, it answers from the web and says so; the strategy would do the same with an empty corpus, although the app still refuses questions until manuals are ingested (ADR 0013).
- Questions, and search queries shaped by the manual findings, leave the app through Anthropic's web search. The README's statement that only prompts to the Anthropic API leave the machine now includes these searches.
- The sample manuals describe fictional products, so the web cannot confirm or contradict them; conflict detection is best seen on real manuals or on the dated UAT corpus.
- The column needs web search to be enabled for the Anthropic organisation (Claude Console). Without it the API rejects every web-phase request, and every question in this column fails after the local phase.
- `max_uses` tracks the remaining search budget, so the tool definitions change after each search and web-phase requests rewrite the prompt cache instead of reading it: a known extra cost in exchange for an exact limit.
- Offline tests use `FakeLLM` scripts for `server_tool_use`, `web_search_tool_result` and `pause_turn` blocks; no test touches the network.

## Revisit when

- Search results are too thin to check claims and full pages are needed (Claude's web fetch tool).
- An organisation needs answers from approved sources only, or a restricted list of domains (the web search tool's domain filters).
- Web search pricing or the tool version changes.
- The shared phase loop proves itself and Agentic should move onto it.
