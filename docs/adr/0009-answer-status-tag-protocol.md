# ADR 0009: Answer status via a trailing tag in the answer text

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Each answer needs a machine-readable status: `answered`, `not_covered` or `contradiction_found`.
The status drives the UI badge and the leaderboard's not-covered rate, and it makes the
"honesty" success criterion measurable.

The answers also need **citations**. Claude's citations feature can't be combined with structured
outputs (`output_config.format`): the API returns a 400 error.

## Options considered

1. **A trailing tag, `<status>…</status>`, at the end of the answer text**
   - **Pros:**
     - Works with citations and with streaming.
     - The same mechanism for all three strategies.
     - Simple to parse.
   - **Cons:**
     - The model could omit the tag or get it wrong, so we need a fallback.
     - The streaming parser must hide the tag even when it arrives split across several pieces.
2. **Structured JSON output**
   - **Pros:** The format is guaranteed.
   - **Cons:**
     - Incompatible with citations.
     - Streaming JSON is harder to show as readable text.
3. **A second, cheap classification call after each answer**
   - **Pros:** Keeps the answer clean.
   - **Cons:**
     - An extra call, extra cost and extra time.
     - The classifier sees only the answer, not the sources.
4. **A `report_status` tool the model must call**
   - **Pros:** Structured.
   - **Cons:**
     - Forced `tool_choice` is unavailable on Opus 5.5.
     - An unforced call may be skipped.
     - It mixes with the agentic strategy's tools.

## Decision

Use option 1:
- The shared answering rules (ADR 0006) tell the model to end with exactly one status tag.
- `uma/strategies/base.py` provides a streaming filter that holds back any text that could be the start of a tag, removes the tag, and reports the status.
- If the tag is missing or malformed, the status defaults to `answered` and a warning is logged.

## Consequences

- The tag parser is a well-tested unit, including tags split across stream chunks.
- Learners see a practical pattern: when two API features conflict, encode light structure in the text.

## Revisit when

- The API allows citations together with structured outputs.
