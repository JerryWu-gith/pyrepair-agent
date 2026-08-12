import json
import subprocess
import sys
from pathlib import Path


def test_summarize_counts_success_attempts_tokens_and_safety_events() -> None:
    from benchmarks.run_benchmark import summarize

    records = [
        {
            "status": "success",
            "attempts": 1,
            "duration_seconds": 2.0,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "regression_count": 0,
            "policy_rejection_count": 0,
        },
        {
            "status": "failed",
            "attempts": 3,
            "duration_seconds": 4.0,
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "regression_count": 2,
            "policy_rejection_count": 1,
        },
    ]

    assert summarize(records) == {
        "case_count": 2,
        "success_rate": 0.5,
        "first_attempt_success_rate": 0.5,
        "average_attempts": 2.0,
        "average_duration_seconds": 3.0,
        "total_prompt_tokens": 30,
        "total_completion_tokens": 15,
        "regression_count": 2,
        "policy_rejection_count": 1,
    }


def test_copy_case_for_run_excludes_hidden_benchmark_metadata(tmp_path: Path) -> None:
    from benchmarks.run_benchmark import copy_case_for_run

    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / "tests").mkdir()
    (source / ".pytest_cache").mkdir()
    (source / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "tests" / "test_app.py").write_text("def test_it(): pass\n", encoding="utf-8")
    (source / "pyproject.toml").write_text("[project]\nname='case'\n", encoding="utf-8")
    (source / "case.json").write_text('{"answer":"secret"}\n', encoding="utf-8")
    (source / ".pytest_cache" / "state").write_text("cached", encoding="utf-8")

    destination = copy_case_for_run(source, tmp_path / "staged")

    assert (destination / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (destination / "tests" / "test_app.py").is_file()
    assert (destination / "pyproject.toml").is_file()
    assert not (destination / "case.json").exists()
    assert not (destination / ".pytest_cache").exists()


def test_jsonl_records_are_appended_and_can_be_resumed(tmp_path: Path) -> None:
    from benchmarks.run_benchmark import append_record, load_records

    result_path = tmp_path / "results" / "run.jsonl"
    append_record(result_path, {"case_id": "case_01", "status": "success"})
    append_record(result_path, {"case_id": "case_02", "status": "failed"})

    assert load_records(result_path) == [
        {"case_id": "case_01", "status": "success"},
        {"case_id": "case_02", "status": "failed"},
    ]
    assert result_path.read_text(encoding="utf-8").count("\n") == 2


def test_select_pending_cases_supports_case_filter_and_resume() -> None:
    from benchmarks.run_benchmark import select_pending_cases

    cases = [
        {"id": "case_01", "category": "condition"},
        {"id": "case_02", "category": "boundary"},
        {"id": "case_03", "category": "state"},
    ]

    assert select_pending_cases(cases, selected_case=None, completed_ids={"case_01"}) == [
        {"id": "case_02", "category": "boundary"},
        {"id": "case_03", "category": "state"},
    ]
    assert select_pending_cases(cases, selected_case="case_02", completed_ids=set()) == [
        {"id": "case_02", "category": "boundary"}
    ]


def test_render_markdown_reports_metrics_and_keeps_failed_cases() -> None:
    from benchmarks.run_benchmark import render_markdown

    records = [
        {
            "case_id": "case_01",
            "category": "condition",
            "model": "deepseek-v4-flash",
            "status": "success",
            "attempts": 1,
            "duration_seconds": 2.0,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "regression_count": 0,
            "policy_rejection_count": 0,
            "failure_reason": None,
        },
        {
            "case_id": "case_02",
            "category": "boundary",
            "model": "deepseek-v4-flash",
            "status": "failed",
            "attempts": 3,
            "duration_seconds": 4.0,
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "regression_count": 1,
            "policy_rejection_count": 2,
            "failure_reason": "max_attempts_exceeded",
        },
    ]

    report = render_markdown(records, "deepseek-v4-flash", Path("results/run.jsonl"))

    assert "Success rate | 50.0%" in report
    assert "First-attempt success rate | 50.0%" in report
    assert "case_02" in report
    assert "max_attempts_exceeded" in report
    assert "deepseek-v4-pro | Not evaluated" in report


def test_render_markdown_does_not_publish_local_absolute_result_path() -> None:
    from benchmarks.run_benchmark import render_markdown

    result_path = Path("D:/private/project/benchmarks/results/run.jsonl")

    report = render_markdown([], "deepseek-v4-flash", result_path)

    assert "D:/private/project" not in report
    assert "`benchmarks/results/run.jsonl`" in report


def test_record_from_artifacts_extracts_tokens_regressions_and_policy_rejections(
    tmp_path: Path,
) -> None:
    from benchmarks.run_benchmark import record_from_artifacts

    artifact_dir = tmp_path / "run"
    artifact_dir.mkdir()
    (artifact_dir / "report.json").write_text(
        json.dumps(
            {
                "status": "success",
                "attempt_count": 2,
                "failure_reason": None,
                "attempts": [
                    {
                        "outcome": "policy_rejected",
                        "changed_files": ["src/app.py"],
                    },
                    {
                        "outcome": "success",
                        "changed_files": ["src/app.py"],
                        "regression_failures": ["tests/test_old.py::test_old"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "model_turn", "prompt_tokens": 10, "completion_tokens": 4}
                ),
                json.dumps(
                    {"type": "model_turn", "prompt_tokens": 3, "completion_tokens": 1}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "fix.patch").write_text("diff --git a/src/app.py b/src/app.py\n", encoding="utf-8")

    record = record_from_artifacts(
        {"id": "case_01", "category": "condition"},
        model="deepseek-v4-flash",
        duration_seconds=1.25,
        artifact_dir=artifact_dir,
    )

    assert record["status"] == "success"
    assert record["attempts"] == 2
    assert record["prompt_tokens"] == 13
    assert record["completion_tokens"] == 5
    assert record["regression_count"] == 1
    assert record["policy_rejection_count"] == 1
    assert record["changed_files"] == ["src/app.py"]
    assert record["candidate_patch"].startswith("diff --git")


def test_run_selected_cases_persists_each_record_and_refreshes_report(tmp_path: Path) -> None:
    from benchmarks.run_benchmark import load_records, run_selected_cases

    result_path = tmp_path / "results" / "run.jsonl"
    report_path = tmp_path / "benchmark-results.md"
    record = {
        "case_id": "case_01",
        "category": "condition",
        "model": "deepseek-v4-flash",
        "status": "success",
        "attempts": 1,
        "duration_seconds": 2.0,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "regression_count": 0,
        "policy_rejection_count": 0,
        "failure_reason": None,
        "changed_files": ["src/app.py"],
        "candidate_patch": "diff --git",
    }

    records = run_selected_cases(
        [{"id": "case_01", "category": "condition"}],
        existing_records=[],
        result_path=result_path,
        report_path=report_path,
        model="deepseek-v4-flash",
        execute_case=lambda case: record,
    )

    assert records == [record]
    assert load_records(result_path) == [record]
    report = report_path.read_text(encoding="utf-8")
    assert "case_01" in report
    assert "Success rate | 100.0%" in report


def test_resume_retries_technical_error_and_reports_latest_case_result(tmp_path: Path) -> None:
    from benchmarks.run_benchmark import (
        append_record,
        completed_case_ids,
        load_records,
        run_selected_cases,
    )

    result_path = tmp_path / "run.jsonl"
    report_path = tmp_path / "report.md"
    error_record = {
        "case_id": "case_01",
        "category": "condition",
        "model": "deepseek-v4-flash",
        "status": "error",
        "attempts": 0,
        "duration_seconds": 1.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "regression_count": 0,
        "policy_rejection_count": 0,
        "failure_reason": "WorkspaceError",
    }
    success_record = {
        **error_record,
        "status": "success",
        "attempts": 1,
        "failure_reason": None,
    }
    append_record(result_path, error_record)

    assert completed_case_ids([error_record]) == set()
    records = run_selected_cases(
        [{"id": "case_01", "category": "condition"}],
        existing_records=[error_record],
        result_path=result_path,
        report_path=report_path,
        model="deepseek-v4-flash",
        execute_case=lambda case: success_record,
    )

    assert records == [success_record]
    assert len(load_records(result_path)) == 2
    report = report_path.read_text(encoding="utf-8")
    assert "Cases | 1" in report
    assert "Success rate | 100.0%" in report


def test_benchmark_cli_help_exposes_case_model_and_resume_controls() -> None:
    completed = subprocess.run(
        [sys.executable, "benchmarks/run_benchmark.py", "--help"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--case" in completed.stdout
    assert "--model" in completed.stdout
    assert "--resume" in completed.stdout
