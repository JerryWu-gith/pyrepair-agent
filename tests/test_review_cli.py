import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_cli_requires_explicit_live_before_any_network_or_output(tmp_path):
    env = dict(os.environ, DEEPSEEK_API_KEY="TEST_MUST_NOT_BE_USED")
    output = tmp_path / "run"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "benchmarks/run_review_evaluation.py"),
            "run",
            "--prepared",
            str(tmp_path / "absent"),
            "--output",
            str(output),
            "--model",
            "deepseek-flash",
            "--repeats",
            "3",
            "--request-cap",
            "36",
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert "explicit --live" in result.stderr
    assert "TEST_MUST_NOT_BE_USED" not in result.stderr
    assert not output.exists()


def test_cli_help_exposes_offline_subcommands():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "benchmarks/run_review_evaluation.py"),
            "--help",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0
    assert "prepare" in result.stdout and "report" in result.stdout


@pytest.mark.parametrize("error_kind", ["api_error", "parse_error"])
def test_cli_stops_after_error_and_writes_partial_report(tmp_path, monkeypatch, error_kind):
    import json

    from benchmarks import run_review_evaluation
    from benchmarks.evaluation import review_evaluation
    from pyrepair.models import ModelTurn
    from tests.test_review_evaluation import APPROVE, make_prepared

    class Client:
        count = 0

        def complete(self, messages, tools):
            self.count += 1
            if self.count == 1:
                if error_kind == "api_error":
                    raise RuntimeError("offline simulated failure")
                return ModelTurn("not JSON", None, (), 10, 5)
            return ModelTurn(APPROVE, None, (), 10, 5)

    client = Client()
    monkeypatch.setattr(review_evaluation, "_client_factory", lambda **kwargs: client)
    prepared = make_prepared(tmp_path)
    output = tmp_path / "run"
    code = run_review_evaluation.main([
        "run", "--live", "--prepared", str(prepared), "--output", str(output),
        "--model", "deepseek-flash", "--repeats", "1", "--request-cap", "12",
    ])
    assert code == 1
    assert client.count == 1
    assert not (output / "requests/0002").exists()
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["planned_requests"] == 12
    assert summary["started_requests"] == 1
    assert sum(arm["not_started"] for arm in summary["arms"].values()) == 11
    assert (output / "report.md").is_file()
