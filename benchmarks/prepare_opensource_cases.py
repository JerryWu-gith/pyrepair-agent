"""Prepare the two registered upstream dev tasks as data; never run their code."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.cases import contained, is_link, load_cases
from benchmarks.evaluation.grading import write_json
from benchmarks.evaluation.opensource_assets import SOURCE_IDS, assemble_case, prepare_source


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=SOURCE_IDS, nargs="+", default=list(SOURCE_IDS))
    parser.add_argument(
        "--cache",
        type=Path,
        required=True,
        help="new source evidence directory (or verified cache with --assemble-only)",
    )
    parser.add_argument("--destination", type=Path, default=ROOT / "benchmarks")
    parser.add_argument(
        "--assemble-only",
        action="store_true",
        help="reuse verified source cache; never access the network",
    )
    args = parser.parse_args(argv)
    summary_path = args.cache / "preparation-summary.json"
    can_record = False
    try:
        if len(args.case) != len(set(args.case)):
            raise ValueError("duplicate source case selection")
        for root in (args.cache, args.destination):
            if any(is_link(path) for path in (root, *root.parents)):
                raise ValueError("preparation roots cannot be linked directories")
        manifest = contained(args.destination, "manifest_opensource_v1.json")
        targets = [manifest]
        for case_id in args.case:
            targets.extend(
                [
                    contained(args.destination, f"manifest_{case_id}.json"),
                    contained(args.destination, f"eval_cases/opensource_v1/{case_id}"),
                    contained(args.destination, f"eval_private/opensource_v1/{case_id}"),
                ]
            )
        if any(target.exists() for target in [summary_path, *targets]):
            raise FileExistsError(
                "refusing to overwrite existing task assets or preparation evidence"
            )
        if args.assemble_only:
            if not args.cache.is_dir():
                raise ValueError("assemble-only requires an existing verified cache")
        else:
            args.cache.mkdir(parents=True, exist_ok=False)
        can_record = True
        if not args.assemble_only:
            for case_id in args.case:
                result = prepare_source(case_id, args.cache / case_id)
                print(f"{case_id}: {result['status']}", flush=True)
        cases = []
        for case_id in args.case:
            source = args.cache / case_id
            draft = assemble_case(case_id, source / "buggy", source / "fixed", args.destination)
            cases.extend(json.loads(draft.read_text(encoding="utf-8"))["cases"])
            print(f"{case_id}: assets_prepared (external tests not run)", flush=True)
        write_json(manifest, {"version": 2, "cases": cases})
        load_cases(manifest)
        write_json(
            summary_path,
            {
                "version": 1,
                "status": "assets_prepared",
                "cases": args.case,
                "manifest": str(manifest.resolve()),
                "external_tests_run": False,
                "model_calls": 0,
                "nodes_status": "declared_not_collected",
            },
        )
        print(f"Manifest: {manifest}", flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if can_record:
            write_json(
                summary_path,
                {
                    "version": 1,
                    "status": "preparation_error",
                    "error": {"type": type(exc).__name__, "message": str(exc)[:2000]},
                    "external_tests_run": False,
                    "model_calls": 0,
                },
            )
        print(f"Source preparation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
