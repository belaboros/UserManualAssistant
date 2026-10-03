# ADR 0011: Switch the default model to Claude Sonnet 5.5

- **Status:** Accepted
- **Date:** 2026-10-04
- **Supersedes:** [ADR 0007](0007-claude-model-selection.md)

## Context

ADR 0007 chose Claude Opus 5.5 for answer quality. When reviewing the spec, the project owner
decided to use Claude Sonnet 5.5 instead. The demo runs for hours of interactive testing, sending
every question three times, so cost per session and speed matter. The comparison stays fair
because all three strategies still share one model (ADR 0006).

Facts about Claude Sonnet 5.5 (`claude-sonnet-5-5`):
- 1M-token context, so the whole-context strategy keeps its full range;
- $2 per 1M input tokens and $10 per 1M output tokens, half of Opus 5.5, with cache reads at $0.20 per 1M;
- supports citations, prompt caching, streaming and tool use;
- default effort is `high`, and the effort levels are recalibrated compared with earlier Sonnet models;
- `thinking: {type: "disabled"}` is rejected. Thinking runs adaptively, or `{type: "between_tools"}` turns it off between tool calls.

The options and their trade-offs are listed in ADR 0007 and still apply.

## Decision

- **Model:** `claude-sonnet-5-5` by default, still configurable with `UMA_MODEL`.
- **Thinking:** adaptive, with `UMA_EFFORT=medium` by default. That's a balance between answer quality and speed for question answering. `low` is the step down if answers are good enough and speed matters more.
- **Fallback:** the server-side refusal fallback stays enabled, in the `"default"` form, which is the only form Sonnet 5.5 accepts on the Claude API.

## Consequences

- Each question costs about half of what it would on Opus 5.5, and answers stream faster.
- Hard questions that combine several manuals may be answered somewhat less well. Setting `UMA_MODEL=claude-opus-5-5` brings back the ADR 0007 setup for a comparison run.
- The API constraints listed in ADR 0007 apply the same way:
  - no forced `tool_choice`;
  - no assistant prefill;
  - citations can't be combined with structured outputs.

## Revisit when

- Ratings show that the answers are limited by the model rather than by retrieval. For example, all three strategies keep scoring low on questions that combine manuals.
