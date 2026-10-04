"""CLI: `python -m uma ingest|serve`."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from uma.config import load_settings
from uma.corpus.ingest import ingest
from uma.corpus.store import CorpusStore
from uma.embedding import Embedder, FastEmbedEmbedder

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_embedder() -> Embedder:
    return FastEmbedEmbedder()


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="uma")
    sub = parser.add_subparsers(dest="command", required=True)
    p_ingest = sub.add_parser("ingest", help="ingest manuals into the corpus store")
    group = p_ingest.add_mutually_exclusive_group()
    group.add_argument("--manuals-dir", type=Path, default=None)
    group.add_argument("--sample", action="store_true", help="use the bundled sample_manuals/")
    p_serve = sub.add_parser("serve", help="run the web app")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "ingest":
        manuals_dir = REPO_ROOT / "sample_manuals" if args.sample else (args.manuals_dir or settings.manuals_dir)
        if not manuals_dir.is_dir():
            print(f"Manuals directory not found: {manuals_dir}", file=sys.stderr)
            return 1
        report = ingest(manuals_dir, CorpusStore(settings.db_path), make_embedder())
        print(f"Ingested {report.manuals} manuals, {report.sections} sections, {report.chunks} chunks")
        if report.skipped:
            print(f"Skipped (no manual.yaml): {', '.join(report.skipped)}")
        return 0

    import uvicorn

    from uma.web import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
