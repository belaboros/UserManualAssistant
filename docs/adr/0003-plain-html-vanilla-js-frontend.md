# ADR 0003: Plain HTML, CSS and vanilla JavaScript for the frontend

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The UI has two pages:
- an ask page with three streaming columns, ratings and a blind-mode toggle;
- a leaderboard.

Learners should be able to open the frontend files and understand them without knowing a
framework or running a build step.

## Options considered

1. **Plain HTML + vanilla JS, served by FastAPI as static files**
   - **Pros:**
     - No build step and no `node_modules`.
     - Every line is readable by anyone who knows basic web technology.
     - `fetch` and `EventSource` cover all our needs.
   - **Cons:**
     - Updating the page by hand is more verbose than in a framework.
     - It doesn't scale to a large UI.
2. **React or Vue single-page app**
   - **Pros:**
     - Component model.
     - Big ecosystem.
   - **Cons:**
     - Needs a build toolchain.
     - Framework concepts distract from the lesson.
     - Too much for two pages.
3. **HTMX with server-rendered templates**
   - **Pros:** Very little JavaScript.
   - **Cons:**
     - Merging three streams into three columns, with blind-mode shuffling done in the browser, fits HTMX's model awkwardly.
     - It's another concept for learners to pick up.

## Decision

Use plain HTML, CSS and vanilla JavaScript (ES modules) in `uma/static/`. Three libraries are loaded
from a CDN:
- **mermaid.js** renders the "How it works" diagrams (ADR 0010);
- **marked** turns the Markdown answers into HTML;
- **DOMPurify** sanitises that HTML before it's inserted into the page.

## Consequences

- No frontend build or install. Editing a file and refreshing the browser is the whole workflow.
- The JavaScript is kept small and split by concern: `app.js` handles the ask page and `leaderboard.js` the leaderboard.

## Revisit when

- The UI grows beyond roughly five pages, or needs complex shared client state.
