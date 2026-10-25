"""Offline workflow comparison: prepare, verify, simulate. NO paid execution route."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.comparison_budget import checked_path, write_new
from benchmarks.evaluation.comparison_journal import run_slots
from benchmarks.evaluation.comparison_pack import prepare_pack, verify_pack
from benchmarks.evaluation.comparison_reporting import render_comparison, summarize_comparison
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.layered_grading import simulated_grade


def _scripted_candidate(slot, folder):
    return {"status": "simulated", "patch": "", "internal_success": None, "duration_seconds": 0.0}


def _scripted_grade(slot, candidate, folder):
    return simulated_grade()


def _save_report(output, summary):
    try:
        write_new(output / "summary.json", summary)
    except FileExistsError:
        if read_json(output / "summary.json") != summary:
            raise ValueError(
                "existing summary differs; old report will not be overwritten"
            ) from None
    path = checked_path(output / "report.md")
    text = render_comparison(summary)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_text(encoding="utf-8") != text:
            raise ValueError(
                "existing report differs; old report will not be overwritten"
            ) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verify", "simulate"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, action="append")
        if name == "prepare":
            command.add_argument("--environment-lock", type=Path, required=True)
            command.add_argument("--model", default="deepseek-flash")
            command.add_argument("--trials", type=int, default=3)
        else:
            command.add_argument("--pack", type=Path, required=True)
        if name != "verify":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifests = args.manifest or [
            ROOT / "benchmarks/manifest_synthetic_v3.json",
            ROOT / "benchmarks/manifest_opensource_v3.json",
        ]
        cases = [case for manifest in manifests for case in load_cases(manifest)]
        if args.command == "prepare":
            output = prepare_pack(
                cases, args.output, args.environment_lock, args.model, args.trials
            )
            print(f"Offline-only pack prepared; no API calls. 产物目录：{output}")
        else:
            pack = verify_pack(args.pack, cases)
            if args.command == "verify":
                print(
                    f"Frozen pack verified; {len(pack['identity']['slots'])} planned slots; no API calls."
                )
            else:
                output = checked_path(args.output)
                if output.is_relative_to(
                    args.pack.absolute() / "p"
                ) or args.pack.absolute().is_relative_to(output):
                    raise ValueError("simulation output overlaps frozen inputs")
                records = run_slots(
                    pack, output, _scripted_candidate, _scripted_grade, simulation=True
                )
                summary = summarize_comparison(pack, records, simulation=True)
                _save_report(output, summary)
                print(
                    f"{summary['kind']}; {summary['finished']}/{summary['planned']} scripted slots; real API calls=0. 产物目录：{output}"
                )
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        # Do not print arbitrary failure messages which could contain upstream content.
        print(
            f"Offline comparison stopped: {type(exc).__name__}; evidence retained.", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
