"""Command line: rag migrate | ingest mpep | search | fetch | collections | eval."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from rag import db
from rag.config import Settings


def _cmd_migrate(settings: Settings, _: argparse.Namespace) -> int:
    conn = db.connect(settings.db_dsn)
    try:
        applied = db.migrate(conn)
    finally:
        conn.close()
    print("applied: " + (", ".join(applied) if applied else "nothing (up to date)"))
    return 0


def _cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    from rag.connectors import mpep
    from rag.ingest import ingest

    if args.connector != "mpep":
        print(f"unknown connector: {args.connector}", file=sys.stderr)
        return 2
    spec, sections = mpep.load(
        Path(args.source), parse_cache=Path(args.cache) if args.cache else None
    )
    report = ingest(spec, sections, settings, force=args.force)
    print(json.dumps(report.__dict__, indent=2))
    return 0


def _cmd_search(settings: Settings, args: argparse.Namespace) -> int:
    from rag.search import Searcher

    s = Searcher(settings)
    try:
        for r in s.search(
            args.query, args.collection or None, args.k, mode=args.mode, rerank=not args.no_rerank
        ):
            print(f"{r.score:8.3f}  {r.id:28}  {r.title[:70]}")
    finally:
        s.close()
    return 0


def _cmd_fetch(settings: Settings, args: argparse.Namespace) -> int:
    from rag.search import Searcher

    s = Searcher(settings)
    try:
        print(json.dumps(s.fetch(args.id, args.collection), indent=2))
    finally:
        s.close()
    return 0


def _cmd_collections(settings: Settings, _: argparse.Namespace) -> int:
    from rag.search import Searcher

    s = Searcher(settings)
    try:
        print(json.dumps(s.list_collections(), indent=2, default=str))
    finally:
        s.close()
    return 0


def _cmd_eval(settings: Settings, args: argparse.Namespace) -> int:
    from rag.evaluate import run, write_report
    from rag.search import Searcher

    s = Searcher(settings)
    try:
        if args.answers:
            from rag.answers import run_answers

            for golden in args.golden:
                report = run_answers(s, Path(golden), args.answers, label=args.label)
                report["mode"], report["rerank"] = "answers", True
                path = write_report(report, Path(args.out))
                print(json.dumps({"report": str(path), **report["summary"]}, indent=2))
            return 0
        for golden in args.golden:
            report = run(
                s, Path(golden), mode=args.mode, rerank=not args.no_rerank, label=args.label
            )
            path = write_report(report, Path(args.out))
            print(json.dumps({"report": str(path), **report["summary"]}, indent=2))
    finally:
        s.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="rag", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    pi = sub.add_parser("ingest", help="ingest a collection")
    pi.add_argument("connector", choices=["mpep"])
    pi.add_argument("source", help="connector source (mpep: directory of chapter PDFs)")
    pi.add_argument("--cache", help="directory for parsed-document cache (skips re-parsing)")
    pi.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    ps = sub.add_parser("search", help="search collections")
    ps.add_argument("query")
    ps.add_argument("-c", "--collection", action="append")
    ps.add_argument("-k", type=int, default=10)
    ps.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default="hybrid")
    ps.add_argument("--no-rerank", action="store_true")
    pf = sub.add_parser("fetch", help="fetch a whole section by chunk or section id")
    pf.add_argument("id")
    pf.add_argument("-c", "--collection")
    sub.add_parser("collections", help="list collections")
    pe = sub.add_parser("eval", help="run retrieval metrics over golden sets")
    pe.add_argument("golden", nargs="+", help="eval/*.yaml files")
    pe.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default="hybrid")
    pe.add_argument("--no-rerank", action="store_true")
    pe.add_argument("--label", default="")
    pe.add_argument(
        "--answers",
        metavar="CHAT_MODEL",
        help="answer-level eval: one chat turn per case with this model, e.g. chat/gpt-oss-20b",
    )
    pe.add_argument("--out", default="eval/reports")
    args = p.parse_args(argv)
    settings = Settings.from_env()
    handlers = {
        "migrate": _cmd_migrate,
        "ingest": _cmd_ingest,
        "search": _cmd_search,
        "fetch": _cmd_fetch,
        "collections": _cmd_collections,
        "eval": _cmd_eval,
    }
    return handlers[args.cmd](settings, args)


if __name__ == "__main__":
    raise SystemExit(main())
