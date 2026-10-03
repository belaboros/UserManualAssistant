# ADR 0006: Same model, settings and answering rules for every strategy

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The demo compares *retrieval strategies*. If the strategies also used different models, prompts or
settings, a better rating could come from any of those differences, and the lesson would be lost.

## Options considered

1. **Hold everything constant except content selection**
   - **Pros:** Any difference in quality comes from how content was chosen. That's a fair, controlled comparison.
   - **Cons:** No strategy gets prompt tuning specific to it.
2. **Tune each strategy separately, for example a cheaper model for RAG**
   - **Pros:** Closer to how each strategy would be run in production.
   - **Cons:** The comparison stops measuring retrieval alone, and the results can't be interpreted.

## Decision

All three strategies use:
- the same model and effort setting (ADR 0007);
- the same system prompt of **shared answering rules** (`uma/strategies/rules.py`):
  - answer only from the provided manual content;
  - cite every claim;
  - give cross-manual procedures as one ordered set of steps;
  - say plainly when the manuals don't cover the question;
  - call out contradictions between manuals and cite both sides;
  - end with a status tag (ADR 0009).

Each strategy may add only an instruction that describes its mechanism. For example, the agentic
strategy is told which tools it has.

RAG and agentic retrieval also share the same search function. So the agentic strategy differs
from RAG only in *who drives the search*: fixed code, or the model.

## Consequences

- Each strategy's explainer can attribute differences in the demo to the retrieval mechanism.
- A strategy-specific optimisation goes in as a fourth, separately named strategy, never as a quiet change to an existing one.

## Revisit when

- The demo's goal changes from "compare retrieval mechanisms" to "compare production-tuned systems".
