# ADR 0007: Claude Opus 5.5 as the default model, with medium effort

- **Status:** Superseded by [ADR 0011](0011-switch-default-model-to-sonnet-5-5.md)
- **Date:** 2026-10-04

## Context

All three strategies share one model (ADR 0006). It must:
- handle a context large enough for the whole-context strategy;
- support citations on documents, prompt caching, streaming and tool use;
- answer well enough that the differences between strategies, not model weakness, dominate.

Model facts, from Anthropic's model table as of 2026-09:

| Model | ID | Context | Input / output, $ per 1M tokens |
|-------|----|---------|-------------------------|
| Claude Opus 5.5 | `claude-opus-5-5` | 1M | $4 / $20 (cache reads $0.20) |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 1M | $2 / $10 (cache reads $0.20) |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 200K | $1 / $5 |
| Claude Fable 5.1 | `claude-fable-5-1` | 1M | $10 / $50 |

## Options considered

1. **Claude Opus 5.5**
   - **Pros:**
     - Anthropic's recommended default.
     - Strong at combining information across documents and at tool use.
     - 1M-token context.
     - Lower price than earlier Opus models.
   - **Cons:** Twice the price of Sonnet 5.5.
2. **Claude Sonnet 5.5**
   - **Pros:** Half the cost and fast.
   - **Cons:** Somewhat weaker reasoning on hard multi-manual questions.
3. **Claude Haiku 4.5**
   - **Pros:** Cheapest and fastest.
   - **Cons:**
     - A 200K context limits the whole-context strategy.
     - Weaker synthesis would blur the comparison.
4. **Claude Fable 5.1**
   - **Pros:** The most capable model.
   - **Cons:**
     - About 2.5 times the price of Opus 5.5.
     - Long turns hurt the interactive demo.

## Decision

- **Model:** `claude-opus-5-5` by default, configurable with `UMA_MODEL`.
- **Thinking:** adaptive. On Opus 5.5, thinking can't be disabled; effort controls how deep it goes.
- **Effort:** `UMA_EFFORT=medium` by default. That suits question answering; raise it to `high` to test whether harder questions improve.
- **Fallback:** the server-side refusal fallback (`fallbacks: "default"`) is enabled, so a safety-classifier false positive is retried on a suitable model instead of failing the column.

## Consequences

- **Expected cost per question:**
  - Whole-context: about $0.05 to $0.30 on the first question for a few hundred thousand tokens, and roughly 20 times less after that, thanks to cache reads.
  - RAG: a few cents.
  - Agentic: a few cents to tens of cents, depending on the number of tool calls.
- **API constraints of Opus 5.5 that the code must follow:**
  - Forced `tool_choice` isn't allowed, so the agent uses `auto`.
  - No assistant prefill.
  - Citations can't be combined with structured outputs (ADR 0009).

## Revisit when

- Cost per session matters more than answer quality. Switch to `claude-sonnet-5-5` with one environment variable.
- A newer model becomes the recommended default.
