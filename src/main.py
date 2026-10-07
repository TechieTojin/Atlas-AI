"""Atlas CLI.

Usage:
    python -m src.main --query "Your research question" [--mode fast|deep]
                       [--documents id1,id2] [--approve-plan] [--output file.md]

The CLI drives the same ResearchService as the web API: runs are persisted,
progress events stream to the console, and plan approval (when enabled) is
interactive.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import ConfigError, load_config
from src.events import EventType
from src.events.bus import STREAM_END
from src.llm import preflight
from src.models.runs import RunMode, RunStatus, SourceScope

logger = logging.getLogger("atlas")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep third-party HTTP chatter out of normal output.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="Atlas — multi-agent research & knowledge engine.",
    )
    parser.add_argument("--query", "-q", help="Research question to investigate.")
    parser.add_argument(
        "--mode", choices=["fast", "deep"], default="deep",
        help="FAST favors responsiveness; DEEP runs the full workflow.",
    )
    parser.add_argument(
        "--documents", default="",
        help="Comma-separated uploaded document IDs to research against.",
    )
    parser.add_argument(
        "--approve-plan", action="store_true",
        help="Pause after planning for interactive plan approval.",
    )
    parser.add_argument(
        "--output", "-o", help="Optional path to also write the Markdown report to."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging."
    )
    return parser


def _handle_approval(service, run_id: str) -> None:
    run = service.get_run(run_id)
    plan = run.plan
    print("\n--- Research plan (awaiting approval) ---")
    print("Subquestions:")
    for i, task in enumerate(plan.tasks, 1):
        print(f"  {i}. {task.subquestion}")
    print("Search queries:")
    for i, q in enumerate(plan.search_queries, 1):
        print(f"  {i}. {q}")
    while True:
        choice = input("\n[a]pprove / [e]dit queries / [c]ancel: ").strip().lower()
        if choice in ("a", "approve"):
            service.approve_plan(run_id)
            return
        if choice in ("c", "cancel"):
            service.cancel(run_id)
            return
        if choice in ("e", "edit"):
            raw = input("Enter search queries separated by ';': ").strip()
            queries = [q.strip() for q in raw.split(";") if q.strip()]
            if queries:
                service.edit_plan(run_id, search_queries=queries)
                print("Plan updated.")
            else:
                print("No queries entered; plan unchanged.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)

    try:
        config = load_config()
        config.validate()
        preflight(config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    query = (args.query or "").strip()
    if not query:
        try:
            query = input("Enter your research question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nNo query provided; exiting.", file=sys.stderr)
            return 1
    if not query:
        print("A non-empty research question is required.", file=sys.stderr)
        return 1

    from src.api.container import Container

    document_ids = [d.strip() for d in args.documents.split(",") if d.strip()]
    scope = SourceScope.WEB_AND_DOCUMENTS if document_ids else SourceScope.WEB
    container = Container(config)
    service = container.research_service

    try:
        run = service.create_run(
            query=query,
            mode=RunMode.FAST if args.mode == "fast" else RunMode.DEEP,
            source_scope=scope,
            document_ids=document_ids,
            approval_required=args.approve_plan,
        )
    except Exception as exc:
        print(f"Could not start research: {exc}", file=sys.stderr)
        return 1

    print(f"Run {run.id} started ({run.mode.value}).")
    _, live = container.bus.subscribe(run.id)
    try:
        while live is not None:
            event = live.get()
            if event is STREAM_END:
                break
            if event.message:
                print(f"  [{event.type.value}] {event.message}")
            if event.type is EventType.WAITING_FOR_PLAN_APPROVAL:
                _handle_approval(service, run.id)
            if event.type.is_terminal:
                break
    except KeyboardInterrupt:
        print("\nCancelling run...", file=sys.stderr)
        try:
            service.cancel(run.id)
        except Exception:
            pass
        return 130

    final = service.get_run(run.id)
    if final.status is not RunStatus.COMPLETED:
        print(f"\nRun finished with status {final.status.value}."
              + (f" {final.error}" if final.error else ""), file=sys.stderr)
        return 1

    print("\n" + "=" * 72 + "\n")
    print(final.final_report)
    m = final.metrics
    print(
        f"\n[{m.total_ms / 1000:.1f}s total | {m.iterations} iteration(s) | "
        f"{m.sources_collected} collected / {m.sources_selected} selected / "
        f"{m.sources_cited} cited | {m.memory_hits} memory hits]"
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(service.export_markdown(run.id))
        print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
