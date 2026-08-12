import subprocess
from pathlib import Path

from pyrepair.testing import TestRunner as PytestRunner

FIXTURES = Path(__file__).parent / "fixtures"


def test_runner_returns_pass_result():
    result = PytestRunner(5).run(FIXTURES / "passing_project")

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.launch_error is None
    assert result.command[-3:] == ("-q", "--tb=short", "--disable-warnings")


def test_runner_returns_failed_result_without_throwing():
    result = PytestRunner(5).run(FIXTURES / "failing_project")

    assert result.exit_code == 1
    assert result.timed_out is False
    assert "FAILED" in result.stdout


def test_runner_marks_timeout(monkeypatch, tmp_path):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(("python", "-m", "pytest"), 0.01)

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    result = PytestRunner(0.01).run(tmp_path)

    assert result.exit_code is None
    assert result.timed_out is True
    assert result.launch_error is None


def test_runner_returns_launch_error(monkeypatch, tmp_path):
    def raise_os_error(*args, **kwargs):
        raise OSError("python unavailable")

    monkeypatch.setattr(subprocess, "run", raise_os_error)

    result = PytestRunner(5).run(tmp_path)

    assert result.exit_code is None
    assert result.launch_error == "python unavailable"


def test_runner_uses_argument_list_without_shell(monkeypatch, tmp_path):
    captured = {}

    def complete(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "1 passed", "")

    monkeypatch.setattr(subprocess, "run", complete)
    target = "tests/test_app.py::test_add"

    result = PytestRunner(5).run(tmp_path, target)

    assert result.exit_code == 0
    assert captured["command"][-1] == target
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["shell"] is False
