"""Explicit fifty-task preparation and authorized supervised evaluation entry."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.catalog_source_cache import write_new_json
from benchmarks.evaluation.goldset_dataset import assemble_dataset, verify_dataset


def _configured_credential():
    # Called by the authorized controller only after frozen identity validation.
    # Prefer the user's persistent setting over a desktop process's stale copy.
    value = None
    try:
        import winreg
    except ImportError:
        pass
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _kind = winreg.QueryValueEx(key, "DEEPSEEK_API_KEY")
        except OSError:
            pass
    if not isinstance(value, str) or not value.strip():
        value = os.environ.get("DEEPSEEK_API_KEY", "")
    if not value.strip():
        raise ValueError("missing configured credential; no API probe is permitted")
    return value.strip()


def _calibrate(cases, lock, output):
    from benchmarks.evaluation.docker_runner import DockerTestRunner
    from benchmarks.evaluation.grading import validate_case

    runner = DockerTestRunner(lock)
    runner.assert_environment_verified()
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in cases[:20]:
        value = validate_case(case, output / case.id, test_runner=runner)
        results.append(value)
        print(f"{case.id}: {value['status']}", flush=True)
        if value.get("system_error"):
            break
    summary = {
        "kind": "offline synthetic task calibration, NOT model performance",
        "planned": 20,
        "finished": len(results),
        "valid": sum(r["status"] == "valid" for r in results),
        "invalid": [r["case_id"] for r in results if r["status"] != "valid"],
    }
    write_new_json(output / "validation-summary.json", summary)
    print(json.dumps(summary), flush=True)
    return 0 if summary["valid"] == 20 else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in (
        "assemble",
        "calibrate-synthetic",
        "prepare",
        "verify",
        "inspect",
        "execute",
        "resume",
    ):
        command = commands.add_parser(action)
        if action == "assemble":
            command.add_argument("--manifest", type=Path, action="append", required=True)
        else:
            command.add_argument("--dataset", type=Path, required=True)
        if action in {"verify", "inspect", "execute", "resume"}:
            command.add_argument("--pack", type=Path, required=True)
        if action != "verify":
            command.add_argument("--output", type=Path, required=True)
        if action in {"prepare", "calibrate-synthetic"}:
            command.add_argument("--environment-lock", type=Path, required=True)
        if action == "prepare":
            command.add_argument("--calibration-root", type=Path, action="append", required=True)
        if action in {"inspect", "execute", "resume"}:
            command.add_argument("--call-limit", type=int, default=5550)
        if action in {"execute", "resume"}:
            command.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "assemble":
            manifest = assemble_dataset(args.manifest, args.output)
            print(f"Fifty-task dataset assembled; API calls=0; manifest: {manifest}")
            return 0
        cases = verify_dataset(args.dataset)
        if args.action == "calibrate-synthetic":
            return _calibrate(cases, args.environment_lock, args.output)
        if args.action in {"prepare", "verify"}:
            from benchmarks.evaluation.goldset_pack import prepare_goldset_pack, verify_goldset_pack

            if args.action == "prepare":
                prepare_goldset_pack(
                    args.dataset, args.output, args.environment_lock, args.calibration_root
                )
                print(f"Fifty-task pack prepared; API calls=0; output: {args.output}")
            else:
                verify_goldset_pack(args.pack, cases)
                print("Fifty-task pack verified; 300 slots; API calls=0")
            return 0
        from benchmarks.evaluation.goldset_live import execute_comparison, inspect_execution

        if args.action == "inspect":
            plan = inspect_execution(args.pack, cases, args.output, "formal", args.call_limit)
            print("NOT AUTHORIZED - inspection only; no credential values or API requests.")
            print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        from benchmarks.evaluation.container_protocol import read_json

        summary = execute_comparison(
            args.pack,
            cases,
            args.output,
            "formal",
            args.call_limit,
            read_json(args.authorization),
            resume=args.action == "resume",
            credential_getter=_configured_credential,
        )
        from benchmarks.evaluation.goldset_reporting import save_goldset_report

        save_goldset_report(cases, summary, args.output)
        print(
            f"Formal goldset evaluation: {summary['finished']}/{summary['planned']}; output: {args.output}",
            flush=True,
        )
        return 2 if any(g["technical_errors"] for g in summary["groups"]) else 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(
            f"Goldset operation stopped: {type(exc).__name__}; evidence retained.",
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
