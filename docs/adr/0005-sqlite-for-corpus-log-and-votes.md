# ADR 0005: SQLite for the corpus, the question log and votes

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

We need to store:
- the parsed corpus: sections, chunks, embeddings and a keyword index;
- every question and its three answers;
- star ratings.

Statistics must stay local and survive restarts, so the leaderboard can be read after a two-hour
session. The corpus is small, a few manuals.

## Options considered

1. **SQLite, one file**
   - **Pros:**
     - Ships with Python.
     - No server to run.
     - FTS5 full-text search (with BM25 ranking) is built in.
     - Easy to copy, back up or open with any SQLite browser.
   - **Cons:**
     - Only one writer at a time. That's irrelevant for a single-user demo.
     - No built-in vector index.
2. **PostgreSQL with pgvector**
   - **Pros:**
     - Production-grade.
     - Real vector index.
   - **Cons:** Needs a server or Docker, which is too heavy for a local demo.
3. **A dedicated vector database (Chroma, Qdrant) plus files for votes**
   - **Pros:** Purpose-built for vectors.
   - **Cons:**
     - Two storage systems.
     - Another dependency to explain.
     - Overkill for a few thousand chunks.
4. **JSON or CSV files**
   - **Pros:** Simplest.
   - **Cons:**
     - No queries.
     - Risk of corrupted writes.
     - Keyword search would have to be hand-written.

## Decision

- One SQLite database at `data/uma.db`, accessed through Python's standard `sqlite3` module.
- Embeddings are stored as `float32` blobs.
- Vector similarity is computed in memory with numpy: a brute-force cosine search over every chunk.
- The `data/` folder is git-ignored.

## Consequences

- Brute-force vector search takes milliseconds at our scale (thousands of chunks), and needs no index to tune.
- Resetting statistics means deleting rows from `votes`. Rebuilding the corpus means running `ingest` again.

## Revisit when

- The corpus grows past about 100,000 chunks, when brute-force search gets slow. Consider `sqlite-vec` or pgvector then.
- Several users write at the same time, on a shared server.
