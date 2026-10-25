"""Explicit adapter-fixed continuation; default inspect never grants API authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.comparison_continuation import execute_continuation, inspect_continuation
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.continuation_assets import prepare_continuation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", choices=("prepare", "inspect", "execute", "resume"), default="inspect"
    )
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--call-limit", type=int, default=1221)
    args = parser.parse_args(argv)
    try:
        cases = [
            c
            for name in ("manifest_synthetic_v3.json", "manifest_opensource_v3.json")
            for c in load_cases(ROOT / "benchmarks" / name)
        ]
        if args.action == "prepare":
            if args.checkpoint is None:
                raise ValueError("pre-change checkpoint required")
            prepare_continuation(args.checkpoint, cases, args.pack)
            print("Prepared adapter-fixed continuation; reused calibration; no API calls.")
        elif args.action == "inspect":
            if args.output is None:
                raise ValueError("output required")
            print("NOT AUTHORIZED - inspection only; no credential access or API calls.")
            print(
                json.dumps(
                    inspect_continuation(args.pack, cases, args.output, args.call_limit),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
            )
        else:
            if args.output is None or args.authorization is None:
                raise ValueError("output and explicit authorization required")
            summary = execute_continuation(
                args.pack,
                cases,
                args.output,
                read_json(args.authorization),
                call_limit=args.call_limit,
                resume=args.action == "resume",
            )
            print(
                f"Continuation: {summary['finished']}/{summary['planned']}; 产物目录：{args.output}"
            )
            if any(g["technical_errors"] for g in summary["groups"]):
                return 2
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(f"Continuation stopped: {type(exc).__name__}; evidence retained.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
