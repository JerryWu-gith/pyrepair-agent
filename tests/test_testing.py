import subprocess
from pathlib import Path

from pyrepair.pytest_capture import CaptureReportError
from pyrepair.testing import TestRunner as PytestRunner

FIXTURES = Path(__file__).parent / "fixtures"


def test_runner_returns_pass_result():
    result = PytestRunner(5).run(FIXTURES / "passing_project")

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.launch_error is None
    assert result.command[2:6] == ("pytest", "-q", "--tb=short", "--disable-warnings")
    assert result.capture_source == "plugin"


def test_runner_returns_failed_result_without_throwing():
    result = PytestRunner(5).run(FIXTURES / "failing_project")

    assert result.exit_code == 1
    assert result.timed_out is False
    assert "FAILED" in result.stdout


def test_runner_loads_structured_call_failure():
    result = PytestRunner(5).run(FIXTURES / "failing_project")

    assert result.capture_source == "plugin"
    assert result.failures[0].node_id == "test_fail.py::test_fail"
    assert result.failures[0].phase == "call"


def test_runner_falls_back_to_text_when_plugin_report_is_invalid(monkeypatch):
    def raise_capture_error(*args, **kwargs):
        del args, kwargs
        raise CaptureReportError("invalid_pytest_capture_report")

    monkeypatch.setattr("pyrepair.testing.load_capture_report", raise_capture_error)

    result = PytestRunner(5).run(FIXTURES / "failing_project")

    assert result.exit_code == 1
    assert result.capture_source == "text"
    assert result.failures[0].node_id == "test_fail.py::test_fail"


def test_runner_captures_setup_and_teardown_failures():
    result = PytestRunner(5).run(FIXTURES / "pytest_capture_project")

    assert {(item.node_id, item.phase) for item in result.failures} == {
        ("test_phases.py::test_setup_error", "setup"),
        ("test_phases.py::test_teardown_error", "teardown"),
    }


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
    assert target in captured["command"]
    assert captured["command"][-2:] == ["-p", "pyrepair.pytest_plugin"]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["env"]["PYREPAIR_PYTEST_REPORT"] == str(
        tmp_path / ".pyrepair" / "internal" / "pytest-report.json"
    )
    assert captured["kwargs"]["shell"] is False
