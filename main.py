"""Entry point: reproducible run of the two demo research queries.

Usage:
  python main.py                # run both demo queries
  python main.py --query broad  # one query only
  python main.py --refresh      # wipe the API cache first (fresh live sources)

Outputs land in outputs/run_<id>/: report markdown, PNG plots, run_<id>.jsonl event log.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from mito_harness.cache import DiskCache
from mito_harness.logging_events import EventBus, new_run_id
from mito_harness.pipeline import build_harness
from setting import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="mito-harness: mitochondrial medicine research review")
    parser.add_argument("--query", choices=["broad", "narrow"], default=None, help="run a single demo query")
    parser.add_argument("--refresh", action="store_true", help="clear the API cache before running")
    return parser.parse_args()


async def run_all(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.refresh:
        DiskCache(settings.paths.cache_dir).clear()

    queries = settings.queries_config["queries"]
    if args.query:
        queries = [q for q in queries if q["id"] == args.query]

    statuses: list[str] = []
    for query in queries:
        run_id = new_run_id()
        bus = EventBus(
            run_id=run_id,
            outputs_dir=settings.paths.outputs_dir,
            console_format=settings.logging.console.format,
            console_enabled=settings.logging.console.enabled,
        )
        harness = build_harness(bus, settings=settings)
        result = await harness.run_query(query["id"], query["text"])
        statuses.append(result.status)
        print(
            f"\n=== query {query['id']}: status={result.status} studies={len(result.records)} "
            f"plots={len(result.plots)} log=outputs/run_{run_id}.jsonl ===",
            flush=True,
        )
        for plot in result.plots:
            print(f"    plot: {plot}")
        report_dir = settings.paths.outputs_dir / f"run_{run_id}"
        for report in sorted(report_dir.glob(f"report_{query['id']}*.md")) if report_dir.exists() else []:
            print(f"    report: {report}")

    return 0 if all(s == "ok" for s in statuses) else 1


def main() -> int:
    result = asyncio.run(run_all(parse_args()))
    print(f"\nDone. Overall status: {'OK' if result == 0 else 'WITH ISSUES'}")
    return result


if __name__ == "__main__":
    sys.exit(main())
