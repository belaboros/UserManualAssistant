# ADR 0008: Local embeddings and SQLite FTS5 for RAG's hybrid search

- **Status:** Accepted
- **Date:** 2026-10-04

## Context

The RAG strategy, and the agentic strategy's `search` tool, need to find relevant chunks. Two
kinds of search complement each other:
- **Keyword search (BM25)** finds exact terms well: product names, error codes, menu labels.
- **Vector search (embeddings)** finds paraphrases well: "reset to factory settings" matches
  "restore defaults".

Anthropic does not offer an embeddings endpoint. The project owner approved sending internal manual
text to Claude. A second cloud provider was not discussed.

## Options considered

1. **Local embedding model (`fastembed`, `BAAI/bge-small-en-v1.5`) plus SQLite FTS5**
   - **Pros:**
     - Internal manual text goes to no provider other than Claude.
     - No second API key.
     - `fastembed` runs on ONNX, so there's no PyTorch download. The model is about 130 MB and runs well on a CPU.
     - FTS5 with BM25 is built into SQLite.
   - **Cons:**
     - Slightly lower retrieval quality than the best hosted embedding models.
     - English-centred.
2. **Hosted embeddings (Voyage AI, which Anthropic recommends, or OpenAI)**
   - **Pros:** Higher-quality embeddings.
   - **Cons:**
     - Internal text goes to a second provider, which hasn't been approved.
     - A second API key and bill.
3. **Vector search only**
   - **Pros:** Simpler.
   - **Cons:** Misses exact-term matches, a classic RAG failure that hybrid search avoids.
4. **Keyword search only**
   - **Pros:** Simplest, nothing to download.
   - **Cons:** Misses paraphrases.

## Decision

Hybrid search in `uma/search.py`:
1. Run FTS5 BM25 and cosine similarity over local `bge-small-en-v1.5` embeddings, taking the top 30 results from each.
2. Merge the two rankings with **Reciprocal Rank Fusion**: `score = Σ 1 / (60 + rank)`.
3. Return the top *k*, which is 8 by default.

The embedding model is downloaded on first `ingest` and cached.

## Consequences

- RAG's retrieval quality is good but not state of the art. The strategy explainer says so, because it's one reason RAG may lose some comparisons.
- Swapping in a hosted embedder later means changing one class, `Embedder`.

## Revisit when

- Manuals in languages other than English are added. Use a multilingual model such as `bge-m3`.
- Sending manual text to an embeddings provider is approved, and retrieval quality becomes the bottleneck.
