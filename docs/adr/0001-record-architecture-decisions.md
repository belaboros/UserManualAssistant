# ADR 0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

This project has an educational purpose: people should be able to learn *why* it is built the way
it is, not only *how*. Technology choices for v1 were delegated to the implementer, so the
reasoning has to be written down where the project owner and learners can review it.

## Options considered

1. **Architecture Decision Records (ADRs), one file per decision.** Small, reviewable, and kept with
   the code. Superseded decisions stay visible.
2. **One big design document.** Easier to read in one go, but decisions get buried, and it's hard
   to see when or why one changed.
3. **No written record (code comments and commit messages only).** The reasoning is scattered and
   lost.

## Decision

Use ADRs in `docs/adr/`, numbered `NNNN-short-title.md`, following a light
[MADR](https://adr.github.io/madr/) structure:

- **Context:** the situation that forces a decision.
- **Options considered:** each option with its pros and cons.
- **Decision:** what was chosen.
- **Consequences:** what becomes easier or harder.
- **Revisit when:** the signals that should reopen the decision.

An ADR is never edited to reverse its decision. A new ADR supersedes it, and the old one's status
changes to `Superseded by ADR NNNN`.

## Consequences

- Every non-obvious technology or architecture choice needs an ADR before or with the code that
  depends on it.
- Learners can read `docs/adr/` in order as a guided tour of the design.

## Revisit when

Never for the practice itself. The template can evolve.
