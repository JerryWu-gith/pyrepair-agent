from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from pyrepair.cli import build_coordinator
from pyrepair.config import ALLOWED_MODELS, AppConfig, ConfigError, load_config
from pyrepair.coordinator import CoordinatorError
from pyrepair.models import RepairRequest


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"JSONL line {line_number} must be an object")
        records.append(value)
    return records


def select_pending_cases(
    cases: list[dict[str, Any]],
    *,
    selected_case: str | None,
    completed_ids: set[str],
) -> list[dict[str, Any]]:
    known_ids = {str(case["id"]) for case in cases}
    if selected_case is not None and selected_case not in known_ids:
        raise ValueError(f"unknown benchmark case: {selected_case}")
    return [
        case
        for case in cases
        if case["id"] not in completed_ids
        and (selected_case is None or case["id"] == selected_case)
    ]


def latest_case_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record["case_id"])] = record
    return list(latest.values())


def completed_case_ids(records: list[dict[str, Any]]) -> set[str]:
    return {
        str(record["case_id"])
        for record in latest_case_records(records)
        if record.get("status") in {"success", "failed"}
    }


def copy_case_for_run(source: Path, destination: Path) -> Path:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "case.json",
            ".pytest_cache",
            ".pyrepair",
            "__pycache__",
            "*.pyc",
        ),
    )
    return destination


def summarize(records: list[dict[str, Any]]) -> dict[str, float | int]:
    if not records:
        return {
            "case_count": 0,
            "success_rate": 0.0,
            "first_attempt_success_rate": 0.0,
            "average_attempts": 0.0,
            "average_duration_seconds": 0.0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "regression_count": 0,
            "policy_rejection_count": 0,
        }

    completed = [record for record in records if record["status"] == "success"]
    count = len(records)
    return {
        "case_count": count,
        "success_rate": len(completed) / count,
        "first_attempt_success_rate": sum(
            record["attempts"] == 1 for record in completed
        )
        / count,
        "average_attempts": sum(record["attempts"] for record in records) / count,
        "average_duration_seconds": sum(
            record["duration_seconds"] for record in records
        )
        / count,
        "total_prompt_tokens": sum(record["prompt_tokens"] for record in records),
        "total_completion_tokens": sum(record["completion_tokens"] for record in records),
        "regression_count": sum(record["regression_count"] for record in records),
        "policy_rejection_count": sum(
            record["policy_rejection_count"] for record in records
        ),
    }


def render_markdown(records: list[dict[str, Any]], model: str, result_path: Path) -> str:
    metrics = summarize(records)
    displayed_result_path = _display_result_path(result_path)
    other_model = (
        "deepseek-v4-pro" if model == "deepseek-v4-flash" else "deepseek-v4-flash"
    )
    lines = [
        "# PyRepair Benchmark Results",
        "",
        f"Raw results: `{displayed_result_path}`",
        "",
        "## Model coverage",
        "",
        "| Model | Status |",
        "| --- | --- |",
        f"| {model} | Evaluated |",
        f"| {other_model} | Not evaluated |",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Cases | {metrics['case_count']} |",
        f"| Success rate | {metrics['success_rate']:.1%} |",
        (
            "| First-attempt success rate | "
            f"{metrics['first_attempt_success_rate']:.1%} |"
        ),
        f"| Average attempts | {metrics['average_attempts']:.2f} |",
        f"| Average duration (seconds) | {metrics['average_duration_seconds']:.2f} |",
        f"| Prompt tokens | {metrics['total_prompt_tokens']} |",
        f"| Completion tokens | {metrics['total_completion_tokens']} |",
        f"| Regressions | {metrics['regression_count']} |",
        f"| Policy rejections | {metrics['policy_rejection_count']} |",
        "",
        "## Cases",
        "",
        "| Case | Category | Status | Attempts | Seconds | Failure reason |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for record in records:
        reason = record.get("failure_reason") or "-"
        lines.append(
            f"| {record['case_id']} | {record['category']} | {record['status']} | "
            f"{record['attempts']} | {record['duration_seconds']:.2f} | {reason} |"
        )

    failures = [record for record in records if record["status"] != "success"]
    lines.extend(["", "## Failed cases", ""])
    if not failures:
        lines.append("None.")
    else:
        for record in failures:
            reason = record.get("failure_reason") or "unknown"
            lines.append(f"- `{record['case_id']}`: `{reason}`")
    lines.append("")
    return "\n".join(lines)


def _display_result_path(path: Path) -> str:
    parts = path.parts
    lowered = [part.lower() for part in parts]
    if "benchmarks" in lowered:
        index = lowered.index("benchmarks")
        return Path(*parts[index:]).as_posix()
    if path.is_absolute():
        return path.name
    return path.as_posix()


def record_from_artifacts(
    case: dict[str, Any],
    *,
    model: str,
    duration_seconds: float,
    artifact_dir: Path,
) -> dict[str, Any]:
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    trace = load_records(artifact_dir / "trace.jsonl")
    turns = [event for event in trace if event.get("type") == "model_turn"]
    attempts = report.get("attempts", [])
    changed_files = sorted(
        {
            path
            for attempt in attempts
            for path in attempt.get("changed_files", [])
            if isinstance(path, str)
        }
    )
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "case_id": case["id"],
        "category": case["category"],
        "model": model,
        "status": report["status"],
        "attempts": report["attempt_count"],
        "duration_seconds": round(duration_seconds, 3),
        "prompt_tokens": sum(int(turn.get("prompt_tokens", 0)) for turn in turns),
        "completion_tokens": sum(int(turn.get("completion_tokens", 0)) for turn in turns),
        "regression_count": sum(
            len(attempt.get("regression_failures", [])) for attempt in attempts
        ),
        "policy_rejection_count": sum(
            attempt.get("outcome") == "policy_rejected" for attempt in attempts
        ),
        "failure_reason": report.get("failure_reason"),
        "changed_files": changed_files,
        "candidate_patch": (artifact_dir / "fix.patch").read_text(encoding="utf-8"),
    }


def run_selected_cases(
    cases: list[dict[str, Any]],
    *,
    existing_records: list[dict[str, Any]],
    result_path: Path,
    report_path: Path,
    model: str,
    execute_case: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    records = latest_case_records(existing_records)
    _write_report(report_path, render_markdown(records, model, result_path))
    for case in cases:
        record = execute_case(case)
        append_record(result_path, record)
        records = latest_case_records([*records, record])
        _write_report(report_path, render_markdown(records, model, result_path))
    return records


def _write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def execute_case(
    case: dict[str, Any],
    *,
    benchmark_root: Path,
    config: AppConfig,
) -> dict[str, Any]:
    started = perf_counter()
    try:
        source = benchmark_root / case["path"]
        with tempfile.TemporaryDirectory(prefix=f"pyrepair-{case['id']}-") as temporary:
            staged = copy_case_for_run(source, Path(temporary) / str(case["id"]))
            coordinator = build_coordinator(config, model_enabled=True)
            try:
                result = coordinator.run(
                    RepairRequest(
                        repo=staged,
                        model=config.model,
                        max_attempts=3,
                    )
                )
                artifact_dir = result.artifact_dir
            except CoordinatorError as exc:
                artifact_dir = exc.artifact_dir
            return record_from_artifacts(
                case,
                model=config.model,
                duration_seconds=perf_counter() - started,
                artifact_dir=artifact_dir,
            )
    except Exception as exc:  # noqa: BLE001 - one broken case must not stop the benchmark
        return {
            "recorded_at": datetime.now(UTC).isoformat(),
            "case_id": case["id"],
            "category": case["category"],
            "model": config.model,
            "status": "error",
            "attempts": 0,
            "duration_seconds": round(perf_counter() - started, 3),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "regression_count": 0,
            "policy_rejection_count": 0,
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "changed_files": [],
            "candidate_patch": "",
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the reproducible PyRepair benchmark suite."
    )
    parser.add_argument("--case", help="Run only one case, for example case_03.")
    parser.add_argument(
        "--model",
        choices=sorted(ALLOWED_MODELS),
        default="deepseek-v4-flash",
        help="DeepSeek model to evaluate.",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="Continue an existing JSONL result file and skip recorded cases.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    benchmark_root = Path(__file__).resolve().parent
    manifest = json.loads((benchmark_root / "manifest.json").read_text(encoding="utf-8"))
    cases = manifest["cases"]
    try:
        config = load_config(require_api_key=True, model_override=args.model)
        if args.resume is not None and not args.resume.is_file():
            raise ValueError(f"resume file does not exist: {args.resume}")
        result_path = args.resume or _new_result_path(benchmark_root, args.model)
        existing_records = load_records(result_path)
        mixed_models = {
            record.get("model") for record in existing_records if record.get("model") != args.model
        }
        if mixed_models:
            raise ValueError("resume file contains records from a different model")
        completed_ids = completed_case_ids(existing_records)
        pending = select_pending_cases(
            cases,
            selected_case=args.case,
            completed_ids=completed_ids,
        )
    except (ConfigError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark configuration error: {exc}", file=sys.stderr)
        return 2

    report_path = benchmark_root.parent / "docs" / "benchmark-results.md"

    def run_one(case: dict[str, Any]) -> dict[str, Any]:
        print(f"[{case['id']}] running {args.model}...")
        record = execute_case(case, benchmark_root=benchmark_root, config=config)
        print(
            f"[{case['id']}] {record['status']} "
            f"attempts={record['attempts']} seconds={record['duration_seconds']:.2f}"
        )
        return record

    records = run_selected_cases(
        pending,
        existing_records=existing_records,
        result_path=result_path,
        report_path=report_path,
        model=args.model,
        execute_case=run_one,
    )
    metrics = summarize(records)
    print(f"Raw JSONL: {result_path}")
    print(f"Markdown report: {report_path}")
    print(f"Success rate: {metrics['success_rate']:.1%} ({metrics['case_count']} cases)")
    return 0


def _new_result_path(benchmark_root: Path, model: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return benchmark_root / "results" / f"{timestamp}-{model}.jsonl"


if __name__ == "__main__":
    raise SystemExit(main())
