"""Explicit controlled live entry. Default inspect grants no paid authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.live_comparison import execute_comparison, inspect_execution
from benchmarks.evaluation.live_plan import absolute_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", choices=("inspect", "execute", "resume"), default="inspect"
    )
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    parser.add_argument("--call-limit", type=int, required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--manifest", type=Path, action="append")
    args = parser.parse_args(argv)
    try:
        manifests = args.manifest or [
            ROOT / "benchmarks/manifest_synthetic_v3.json",
            ROOT / "benchmarks/manifest_opensource_v3.json",
        ]
        cases = [c for path in manifests for c in load_cases(path)]
        if args.action == "inspect":
            plan = inspect_execution(args.pack, cases, args.output, args.mode, args.call_limit)
            print("NOT AUTHORIZED - inspection only; no credential read or API requests.")
            print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
        else:
            if args.authorization is None:
                raise ValueError("explicit execution authorization is required")
            value = read_json(absolute_path(args.authorization))
            summary = execute_comparison(
                args.pack,
                cases,
                args.output,
                args.mode,
                args.call_limit,
                value,
                resume=args.action == "resume",
            )
            print(
                f"Controlled {args.mode}: {summary['finished']}/{summary['planned']}; 产物目录：{args.output}"
            )
            if any(g["technical_errors"] for g in summary["groups"]):
                return 2
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(
            f"Controlled comparison stopped: {type(exc).__name__}; evidence retained.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
