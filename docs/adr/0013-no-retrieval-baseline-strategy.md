# ADR 0013: A no-retrieval baseline strategy as a control group

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The demo compares three retrieval strategies (ADR 0006), but nothing shows what the model can do
*without* retrieval. Without that reference point a learner can't tell whether a good answer came
from the manuals or from what the model already knew, and can't see the failure that retrieval
exists to prevent: fluent, plausible answers about products, internal documents or recent events
the model has never seen.

A fourth column, the **no-retrieval baseline**, fills that gap. It sends only the question: no
manual content, no documents, no tools. The open question is what system prompt it gets. The
shared `ANSWERING_RULES` start with "answer using ONLY the manual content provided" and require a
citation for every claim, which the baseline cannot follow because nothing is provided.

## Options considered

1. **Own rules: answer from your own knowledge (`BASELINE_RULES`)**
   - **Pros:**
     - The instructions match the situation, so the answers show the model's real behaviour.
     - It can ask the model to admit when it doesn't know or may be out of date because of its training cutoff, and not to invent dates, numbers or names. That is the honest version of a baseline.
     - It keeps the same three status tags (ADR 0009), so badges, the `not_covered` rate on the leaderboard, and the status parsing all work unchanged.
   - **Cons:**
     - A second rules text to maintain next to `ANSWERING_RULES`.
     - The prompt differs from the other strategies, so it is not a pure "same prompt, no content" experiment.
2. **Shared `ANSWERING_RULES`, with no content**
   - **Pros:** Literally the same prompt as the other strategies; only the content is missing.
   - **Cons:**
     - The rules forbid outside knowledge and refer to manuals that aren't there, so the model would almost always say `not_covered`. The column would teach nothing about what the model knows.
     - The instruction to cite every claim can't be followed.
3. **No system prompt at all**
   - **Pros:** The rawest view of the model; nothing to maintain.
   - **Cons:**
     - No status tag, so every answer would be logged as `answered` with a missing-tag warning, and the `not_covered` comparison would be lost.
     - Nothing discourages invented specifics, and answers would be longer and in a different style from the other columns, which makes blind comparison harder.

## Decision

Use option 1:
- `BASELINE_RULES` in `uma/strategies/rules.py`: answer from your own knowledge; say plainly when you don't know or your information may be out of date because of your training cutoff; don't invent specifics you're unsure of; be concise; end with exactly one status tag (`answered`, `not_covered` for unknown or after-cutoff, `contradiction_found` only for genuinely conflicting authoritative information).
- `BaselineStrategy` in `uma/strategies/baseline.py` (id `baseline`, title "No retrieval") sends `BASELINE_RULES` as the system prompt and the plain question as the only user message, through the shared `run_single_call`. It takes no corpus store or embedder.
- It is the first entry in `STRATEGY_ORDER` and the leftmost column in the UI.

## Consequences

- This is not a deviation from ADR 0006. The baseline uses the same model, effort, adaptive thinking and server-side fallback through the same LLM wrapper. Only the rules text differs, and only because there is no content to answer from or cite. ADR 0006 already says a new idea goes in as a separately named strategy, which this is.
- Every question now makes one extra, small model call (a couple of hundred input tokens plus the answer), which adds a little to cost per question and nothing noticeable to latency, since the strategies run in parallel.
- The baseline's answers never have citations, and its status is the model's self-assessment rather than a judgement about the manuals. The explainer and the demo questions point this out.
- In blind mode the baseline column is often recognisable because it has no `[n]` markers. That is inherent to the comparison.
- The live smoke test (`tests/test_live.py`) still checks the three retrieval strategies only, since it asserts that the manuals' planted contradiction is found.

## Revisit when

- The model's training data starts to include the sample manuals (for example if they are published widely), so the baseline stops being a clean "knows nothing about this product" reference.
- The demo adds web search or other non-manual sources, which would need their own column rather than changing the baseline.
