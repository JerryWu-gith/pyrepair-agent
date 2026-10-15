import os
import subprocess
import sys
from pathlib import Path

from tests.evaluation_helpers import make_case

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    env = {k: v for k, v in os.environ.items() if k not in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}}
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(ROOT / "benchmarks/run_evaluation.py"), *map(str, args)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )


def test_offline_commands_need_no_key_and_have_meaningful_exit_codes(tmp_path):
    manifest = make_case(tmp_path / "bank")
    assert run("--help").returncode == 0
    result = run("validate", "--manifest", manifest, "--output", tmp_path / "validation")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "validation/demo/validation.json").exists()
    result = run(
        "grade",
        "--manifest",
        manifest,
        "--case",
        "demo",
        "--patch",
        tmp_path / "bank/private/demo/wrong.patch",
        "--output",
        tmp_path / "grade",
    )
    assert result.returncode == 1, result.stderr
    assert "hidden_failed" in result.stdout
    result = run("run", "--manifest", manifest, "--case", "demo", "--output", tmp_path / "exp")
    assert result.returncode == 2
    assert "DEEPSEEK_API_KEY" in result.stderr
    assert not (tmp_path / "exp").exists()


def test_report_does_not_rerun_agent(tmp_path):
    from benchmarks.evaluation.cases import load_cases
    from benchmarks.evaluation.experiment import create_experiment

    path = create_experiment(
        load_cases(make_case(tmp_path / "bank")), tmp_path / "exp", "deepseek-v4-flash", 1
    )
    result = run("report", "--experiment", path)
    assert result.returncode == 0, result.stderr
    assert (path / "report.md").exists()
    assert "0/1" in (path / "report.md").read_text(encoding="utf-8")


def test_report_includes_unfinished_execution_usage_as_lower_bound(tmp_path):
    import json

    import pytest

    from benchmarks.evaluation.cases import load_cases
    from benchmarks.evaluation.experiment import create_experiment, run_experiment
    from tests.test_evaluation_experiment import write_raw_result

    cases = load_cases(make_case(tmp_path / "bank"))
    path = create_experiment(cases, tmp_path / "exp", "deepseek-v4-flash", 1)

    def interrupt(case, output, model):
        write_raw_result(output, case.gold_patch.read_text())
        trace = output / ".pyrepair/runs/evaluation/trace.jsonl"
        trace.write_text(
            json.dumps(
                {
                    "type": "model_turn",
                    "role": "repair",
                    "prompt_tokens": 17,
                    "completion_tokens": 4,
                }
            )
            + "\n"
        )
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_experiment(path, cases, agent_executor=interrupt)
    assert run("report", "--experiment", path).returncode == 0
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] == 0
    assert summary["cost_complete"] is False
    assert summary["tokens"]["repair"]["prompt_tokens"] is None
    assert summary["known_tokens"]["repair"]["prompt_tokens"] == 17
    assert summary["unfinished_executions"] == 1


def test_zero_trials_is_rejected_before_any_executor(tmp_path, monkeypatch):
    import pytest

    from benchmarks import run_evaluation

    manifest = make_case(tmp_path / "bank")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-canary-not-a-real-key")

    def forbidden(*args):
        pytest.fail("zero trials must never reach the executor")

    monkeypatch.setattr(run_evaluation, "run_experiment", forbidden)
    output = tmp_path / "experiment"
    assert (
        run_evaluation.main(
            ["run", "--manifest", str(manifest), "--trials", "0", "--output", str(output)]
        )
        == 2
    )
    assert not output.exists()
