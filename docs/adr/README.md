# Architecture Decision Records

Each file records one decision: the context, the options considered, what was chosen and why, and
when to revisit it. Read them in order for a guided tour of the design. See
[ADR 0001](0001-record-architecture-decisions.md) for the format.

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-python-fastapi-backend.md) | Python with FastAPI for the backend | Accepted |
| [0003](0003-plain-html-vanilla-js-frontend.md) | Plain HTML, CSS and vanilla JavaScript frontend | Accepted |
| [0004](0004-server-sent-events-for-streaming.md) | Server-Sent Events for streaming answers | Accepted |
| [0005](0005-sqlite-for-corpus-log-and-votes.md) | SQLite for the corpus, question log and votes | Accepted |
| [0006](0006-same-model-and-rules-for-all-strategies.md) | Same model, settings and answering rules for every strategy | Accepted |
| [0007](0007-claude-model-selection.md) | Claude Opus 5.5 as the default model, with medium effort | Superseded by 0011 |
| [0008](0008-local-embeddings-and-fts5-for-rag.md) | Local embeddings and SQLite FTS5 for RAG's hybrid search | Accepted |
| [0009](0009-answer-status-tag-protocol.md) | Answer status via a trailing tag in the answer text | Accepted |
| [0010](0010-mermaid-for-diagrams.md) | Mermaid for architecture and strategy diagrams | Accepted |
| [0011](0011-switch-default-model-to-sonnet-5-5.md) | Switch the default model to Claude Sonnet 5.5 | Accepted |
| [0012](0012-citation-mechanism-per-strategy.md) | Citation mechanism per strategy | Accepted |
