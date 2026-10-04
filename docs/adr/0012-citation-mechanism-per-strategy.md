# ADR 0012: Citation mechanism per strategy

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

Every strategy must cite the manual sections behind its answer, and the answer text uses `[n]`
markers that index into `Answer.citations` (ADR 0006).

The three strategies hand content to Claude in different ways:
- **Whole-context** and **RAG** send the manual content as `document` blocks. Claude's native
  citations feature then returns a `content_block_location` for each cited passage. It maps
  exactly to one section and includes the quoted text (`cited_text`).
- **Agentic** gives Claude tools. The content arrives as plain text in `tool_result` blocks, so
  there is no document block for a native citation to point to.

## Options considered

1. **Native citations for whole-context and RAG; `[§section_id]` markers for agentic**
   - **Pros:**
     - Each strategy uses the simplest mechanism that fits how it delivers content.
     - Native citations give an exact, verifiable quoted text.
     - The marker protocol is small: the code resolves each marker to a section, and unknown ids are dropped.
   - **Cons:**
     - Two mechanisms to maintain.
     - The agentic citations carry no `cited_text` quote.
     - The model could cite a section it never read; we only check that the section exists.
2. **Native citations everywhere, with `search_result` blocks inside tool results**
   - **Pros:** One mechanism, with quoted text for the agentic strategy too.
   - **Cons:**
     - More API surface to learn and test.
     - The tool results become less transparent: learners see structured blocks instead of the plain text the model reads.
3. **Markers everywhere**
   - **Pros:** One mechanism, and a trivial one.
   - **Cons:**
     - Loses the native-citation lesson, which is one of the points of the comparison.
     - Loses the exact quoted text for whole-context and RAG.

## Decision

Use option 1:
- Whole-context and RAG use native document citations.
- The agentic strategy cites with `[§<section_id>]` markers. `resolve_section_markers` in `uma/strategies/base.py` replaces each marker with `[n]` and builds the `Citation` from the corpus store.
- The system prompt for the agentic strategy describes the marker format (`AGENTIC_ADDENDUM`).

## Consequences

- In the comparison, the agentic column shows citations without `cited_text` quotes.
- Both mechanisms end in the same `Citation` objects, so the UI and the evaluation code do not care which one produced them.
- Markers are plain text, so a model slip such as a made-up section id is silently dropped rather than shown.

## Revisit when

- Native citations over `search_result` blocks in tool results become the documented way to cite tool output, and the lost quotes matter to readers.
