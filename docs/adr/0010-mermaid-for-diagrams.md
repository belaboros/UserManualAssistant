# ADR 0010: Mermaid for architecture and strategy diagrams

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The project's educational goal needs diagrams:
- a system overview;
- for each strategy, a flowchart of where information travels;
- for each strategy, a sequence diagram of one question.

The diagrams should stay accurate as the code changes. The app's "How it works" panel should show
the same diagrams as the docs.

## Options considered

1. **Mermaid, as text in Markdown**
   - **Pros:**
     - Diagrams are plain text, so they're reviewed in diffs.
     - GitHub renders them inline.
     - mermaid.js renders the same source in the browser.
     - Flowcharts and sequence diagrams are both supported.
   - **Cons:** Limited control over layout.
2. **draw.io or Excalidraw files exported as images**
   - **Pros:** Full visual control, and they look polished.
   - **Cons:**
     - Binary or noisy files.
     - Images drift out of date.
     - Two copies are needed, one for the docs and one for the app.
3. **PlantUML**
   - **Pros:** Expressive text format.
   - **Cons:**
     - Needs Java or a render server.
     - GitHub doesn't render it natively.
4. **ASCII art**
   - **Pros:** Works everywhere.
   - **Cons:** Hard to maintain, and sequence diagrams are hard to read.

## Decision

- All diagrams are Mermaid.
- The strategy diagrams are written once, in `uma/static/diagrams/*.mmd`.
- The docs embed them as fenced `mermaid` code blocks.
- A test checks that each block in the docs matches its `.mmd` source, so the docs and the app can't drift apart.
- The app renders the `.mmd` files with mermaid.js.

## Consequences

- Changing a strategy's flow means updating one `.mmd` file and copying it into the doc. The test catches a forgotten copy.

## Revisit when

- Diagrams need visual polish for a presentation. Export the Mermaid diagrams to SVG, or redraw them for that purpose only.
