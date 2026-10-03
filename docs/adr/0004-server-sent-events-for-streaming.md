# ADR 0004: Server-Sent Events (SSE) for streaming answers

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Three strategies answer at the same time, and each one streams text, research-trace steps and a
final result. The browser has to show all three as they arrive. Streaming makes the speed
differences between strategies visible, which is part of the lesson.

## Options considered

1. **Server-Sent Events: one stream per question, carrying events from all three strategies**
   - **Pros:**
     - One-way, server-to-browser streaming, which is exactly the need.
     - Plain HTTP.
     - The browser's built-in `EventSource` API.
     - Easy to inspect in the browser's developer tools.
   - **Cons:** Server-to-browser only. That's fine here: votes are ordinary `POST` requests.
2. **WebSockets**
   - **Pros:** Two-way.
   - **Cons:**
     - More protocol and connection handling.
     - We don't need two-way traffic.
3. **Three separate SSE streams, one per strategy**
   - **Pros:** Each stream is simpler.
   - **Cons:** Three connections per question, and harder to persist the combined result in one place.
4. **No streaming: return the three answers together when all are done**
   - **Pros:** Simplest.
   - **Cons:**
     - The fast strategy waits for the slow one.
     - Latency differences disappear from view.

## Decision

1. `POST /api/questions` creates the question and returns its ID.
2. `GET /api/questions/{id}/stream` is a single SSE stream. Each event is JSON with `strategy` and
   `type` fields (`delta`, `trace`, `final`, `failed`), followed by a closing `done` event.

## Consequences

- The backend merges three async iterators into one stream (`runner`).
- The browser routes each event to a column by its `strategy` field.

## Revisit when

- Multi-turn conversations or interrupting an answer mid-way need two-way messaging.
