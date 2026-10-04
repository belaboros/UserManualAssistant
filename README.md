# UserManualAssistant

AI assistant on a small set of user manuals that
 - answers questions across one or more manuals
 - reports gaps, incosistencies to authors of the user manuals
 - reports uncovered expectations and new use-cases to the authors
 - if the AI assistant cannot help, then it offers schedulin a consultation session with the authors of the related user manuals at the first available timeslot     

## Purpose
* Users don't want to read long user manuals any more. Let them ask questions directly and the AI assistant will answer it.
* Users don't want to be scattered/lost between multipe user manuals for their overarching tasks.
* Authors of the user manuals want to know about bugs, gaps and inconsistencies, redundancies in their user manuals.<br>Created automatically by the AI assistant.
* Authors of the user manuals want to know about new use-cases and uncovered expectations of their users.<br>Created automatically by the AI assistant.

Summary<br>
Users want quick and efficient solutions to their problem, rather than reading long manuals, waiting long for a personal consultation or reporting bugs manually in a ticketing system, ... 


## v1: retrieval strategy comparison

The first version is a side-by-side lab for one question: *how should an assistant find the right passage in a set of user manuals?* You ask a question once and five strategies answer it in parallel, each streaming into its own column, all using the same Claude model. Three manuals-only retrieval strategies share the same answering rules; a no-retrieval baseline shows what the model knows on its own; and a fifth strategy also checks the web:

* **No retrieval** sends only the question, so you can see what the model knows on its own (the control group).
* **Whole-context** puts every manual into the prompt.
* **RAG** retrieves the most relevant chunks with local embeddings and full-text search, then answers from them.
* **Agentic** lets Claude search and read the manuals with tools until it is satisfied.
* **Agentic & web** researches the manuals like Agentic, then searches the web with Claude's web search tool, and merges both into one answer. Where the web disagrees with a manual it shows a "⚠ Conflict: the manual may be out of date" block, citing both sides.

Each column shows the answer, its citations, a trace of the steps taken, and the time, token and cost figures. You can judge the answers yourself: vote for the best one, optionally in **blind mode**, which hides which strategy produced which column until you have voted. The ⤢ button in a column header maximizes that column (the others shrink to clickable strips); ⤡, `Esc` or clicking its title restores equal widths. The **leaderboard** page (`/leaderboard`) aggregates the votes, with filtering, export and reset.

What you can learn from it: where each strategy is accurate, fast and cheap, where it misses content or gets expensive, and how each one handles questions the manuals do not cover or answer inconsistently. The sample corpus contains a deliberate contradiction (the thermostat factory-reset hold time) so you can see which strategies notice it.

The only data stored is local, in `data/uma.db` (the ingested corpus, the question log and your votes). Nothing is sent anywhere except the prompts to the Anthropic API; for the Agentic & web column that includes web searches, which Anthropic runs on the web.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and an Anthropic API key.

```bash
uv sync
cp .env.example .env          # then set ANTHROPIC_API_KEY in .env
uv run python -m uma ingest --sample
uv run python -m uma serve
```

Then open http://127.0.0.1:8000. The first `ingest` downloads a small local embedding model (about 130 MB). Use `uv run python -m uma serve --host HOST --port PORT` to change the address.

## Using your own manuals

Put each manual in its own folder under `manuals/` (git-ignored, so your documents stay out of the repository) and describe it with a `manual.yaml`:

```
manuals/
  my-router/
    manual.yaml
    setup.md
    troubleshooting.html
```

```yaml
title: My Router            # required
id: my-router               # optional, defaults to the folder name
owner: Support team         # optional
visibility: internal        # optional: internal (default) or external
base_url: https://example.com/docs/my-router/   # optional, used to build links to sections
```

Supported file types are `.md`, `.markdown`, `.html` and `.htm`, found recursively inside the folder. Folders without a `manual.yaml` are skipped. Then run:

```bash
uv run python -m uma ingest                          # reads manuals/ (or UMA_MANUALS_DIR)
uv run python -m uma ingest --manuals-dir PATH       # reads another directory
```

## Learn how it works

* [Architecture overview](docs/architecture/overview.md)
* The five strategy explainers: [no retrieval](docs/strategies/0-baseline.md), [whole-context](docs/strategies/1-whole-context.md), [RAG](docs/strategies/2-rag.md), [agentic](docs/strategies/3-agentic.md), [agentic & web](docs/strategies/4-agentic-web.md)
* [Choosing a strategy](docs/choosing-a-strategy.md)
* [Demo questions](docs/demo-questions.md) to try in the app
* [Architecture decision records](docs/adr/README.md)

## Running tests

```bash
uv run pytest             # offline unit and integration tests
uv run pytest -m live     # smoke test against the real Claude API (a few cents; needs credentials)
```
