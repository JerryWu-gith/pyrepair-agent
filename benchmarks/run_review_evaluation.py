"""Fixed Review comparison: prepare/report offline; run requires explicit --live."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.review_evaluation import _redact, run_review
from benchmarks.evaluation.review_fixtures import prepare_review
from benchmarks.evaluation.review_reporting import write_report
from pyrepair.recorder import RecorderError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, default=ROOT / "benchmarks/manifest_v2.json")
    prepare.add_argument("--fixtures", type=Path, default=ROOT / "benchmarks/review_cases")
    prepare.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--live", action="store_true")
    run.add_argument("--prepared", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--repeats", type=int, required=True)
    run.add_argument("--request-cap", type=int, required=True)
    report = commands.add_parser("report")
    report.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            path = prepare_review(args.manifest, args.fixtures, args.output)
            print(f"Offline preparation complete (NOT model performance).\n产物目录：{path}")
        elif args.command == "report":
            write_report(args.experiment)
            print(args.experiment.resolve() / "report.md")
        else:
            path = run_review(
                args.prepared,
                args.output,
                live=args.live,
                model=args.model,
                repeats=args.repeats,
                request_cap=args.request_cap,
            )
            summary = write_report(path)
            print(f"产物目录：{path}")
            if any(
                a["api_errors"] or a["parse_errors"] or a["pending_started"] or a["not_started"]
                for a in summary["arms"].values()
            ):
                return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError, RecorderError) as exc:
        print(_redact(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
