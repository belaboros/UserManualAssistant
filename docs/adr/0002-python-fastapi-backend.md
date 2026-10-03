# ADR 0002: Python with FastAPI for the backend

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The backend must:
- parse HTML and Markdown;
- compute embeddings locally;
- run hybrid search;
- call the Claude API with streaming, citations and tool use;
- stream three answers at once to a browser.

The project owner had no stack preference. The code should be easy for learners to read.

## Options considered

1. **Python + FastAPI**
   - **Pros:**
     - Most retrieval and LLM teaching material is written in Python.
     - Mature libraries for every step: `anthropic`, `markdown-it-py`, `selectolax`, `fastembed`, `numpy`.
     - FastAPI's `async` model suits running three strategies in parallel, and it streams responses natively.
     - Type hints and Pydantic make the data shapes self-documenting.
   - **Cons:** The UI and the backend are in different languages.
2. **TypeScript (Node / Next.js)**
   - **Pros:**
     - One language end to end.
     - An excellent Anthropic SDK.
   - **Cons:**
     - Local embedding and text-processing libraries are less mature.
     - Next.js adds framework concepts that distract from the retrieval lesson.
3. **Python + Flask or Django**
   - **Pros:** Familiar.
   - **Cons:**
     - Flask's async and streaming support is clumsier.
     - Django is too heavy for a demo with three pages.

## Decision

- Python 3.12, FastAPI and Uvicorn.
- Dependencies managed with **uv**, declared in `pyproject.toml`. uv is fast, gives reproducible installs with a lockfile, and one command creates the virtual environment.
- Tests with **pytest** and **pytest-asyncio**.

## Consequences

- Running the app needs Python 3.12 and uv (`uv sync`, then `uv run python -m uma serve`).
- The frontend stays deliberately thin (see ADR 0003), so having two languages costs little.

## Revisit when

- The app needs a rich interactive frontend, where a TypeScript framework would pay off.
- The company's deployment platform requires a different runtime.
