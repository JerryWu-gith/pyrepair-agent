"""Evaluation v2 CLI. Only `run` can call a paid model."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
# Prefer this checkout even if a shared venv is editable-installed elsewhere.
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.execution_policy import require_case_backend, require_live_cases
from benchmarks.evaluation.experiment import (
    create_experiment,
    load_config,
    report_records,
    run_experiment,
)
from benchmarks.evaluation.grading import grade_patch, validate_case, write_json
from benchmarks.evaluation.reporting import render_report, summarize


def new_output(kind):
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    return ROOT / "benchmarks/results/v2" / (kind + "-" + name)


def save_report(path, records):
    config = load_config(path)
    write_json(path / "summary.json", summarize(config, records))
    temp = path / "report.md.tmp"
    temp.write_text(render_report(config, records), encoding="utf-8")
    temp.replace(path / "report.md")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "grade", "run"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, default=ROOT / "benchmarks/manifest_v2.json")
        command.add_argument("--case", required=name == "grade")
        command.add_argument("--output", type=Path)
        if name in {"validate", "grade"}:
            command.add_argument("--backend", choices=("synthetic", "docker"), default="synthetic")
            command.add_argument("--environment-lock", type=Path)
        if name == "grade":
            command.add_argument("--patch", type=Path, required=True)
        if name == "run":
            command.add_argument("--model")
            command.add_argument("--trials", type=int)
            command.add_argument("--resume", type=Path)
    report = commands.add_parser("report")
    report.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            save_report(args.experiment, report_records(args.experiment))
            print(args.experiment / "report.md")
            return 0
        cases = load_cases(args.manifest)
        if args.case:
            cases = [c for c in cases if c.id == args.case]
            if not cases:
                raise ValueError(f"unknown case: {args.case}")
        if args.command == "run":
            require_live_cases(cases)
        else:
            backend = args.backend
            if (backend == "docker") != (args.environment_lock is not None):
                raise ValueError(
                    "--backend docker and --environment-lock must be supplied together"
                )
            source_kinds = {case.source_kind for case in cases}
            if len(source_kinds) > 1:
                raise ValueError("mixed source_kind datasets are not supported")
            if backend == "synthetic" and args.environment_lock is not None:
                raise ValueError("--environment-lock requires --backend docker")
            test_runner = None
            if backend == "docker":
                from benchmarks.evaluation.docker_runner import DockerTestRunner

                test_runner = DockerTestRunner(args.environment_lock)
            else:
                from benchmarks.evaluation.grading import run_tests

                test_runner = run_tests
            for case in cases:
                require_case_backend(case, backend, test_runner)
        output = args.output or new_output(args.command)
        if args.command == "validate":
            output.mkdir(parents=True, exist_ok=False)
            results = []
            for case in cases:
                result = validate_case(case, output / case.id, test_runner=test_runner)
                results.append(result)
                print(f"{case.id}: {result['status']}", flush=True)
            summary = {
                "candidate_tasks": len(cases),
                "valid": sum(r["status"] == "valid" for r in results),
                "invalid": [r["case_id"] for r in results if r["status"] != "valid"],
                "kind": "offline task validation, NOT model evaluation",
            }
            write_json(output / "validation-summary.json", summary)
            print(f"产物目录：{output}")
            return (
                2
                if any(result.get("system_error") for result in results)
                else 0
                if summary["valid"] == len(cases)
                else 1
            )
        if args.command == "grade":
            result = grade_patch(
                cases[0],
                args.patch.read_text(encoding="utf-8"),
                output,
                test_runner=test_runner,
            )
            print(f"{result['status']}\n产物目录：{output}")
            return (
                0
                if result["status"] == "passed"
                else 2
                if result["status"] in {"environment_error", "grader_error", "timeout"}
                else 1
            )
        if args.resume:
            if args.output:
                raise ValueError("--output cannot be combined with --resume")
            output = args.resume
            config = load_config(output)["identity"]
            for key in ("model", "trials"):
                requested = getattr(args, key)
                if requested is not None and requested != config[key]:
                    raise ValueError(f"resume {key} conflicts with saved identity")
            selected = [c["id"] for c in config["cases"]]
            if args.case and selected != [args.case]:
                raise ValueError("resume case selection conflicts with saved identity")
            by_id = {c.id: c for c in cases}
            cases = [by_id[cid] for cid in selected]
        if not os.getenv("DEEPSEEK_API_KEY"):
            raise ValueError("missing DEEPSEEK_API_KEY; no model request was made")
        print("注意：run 将调用真实模型并产生 API 费用。", flush=True)
        if not args.resume:
            output = create_experiment(
                cases,
                output,
                args.model or "deepseek-flash",
                args.trials if args.trials is not None else 1,
            )
        records = run_experiment(output, cases)
        save_report(output, records)
        print(f"产物目录：{output}")
        return (
            2
            if any(r["agent"]["status"] in {"executor_error", "environment_error"} for r in records)
            else 0
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"评测错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
