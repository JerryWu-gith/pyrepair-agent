import json
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


def test_runner_ignores_stale_report_when_cleanup_and_plugin_write_fail(monkeypatch, tmp_path):
    repo = tmp_path / "candidate"
    repo.mkdir()
    (repo / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n", encoding="utf-8")
    (repo / "test_current.py").write_text(
        "def test_current_failure():\n    assert False, 'current failure'\n",
        encoding="utf-8",
    )
    (repo / "conftest.py").write_text(
        """from __future__ import annotations

import os
from pathlib import Path

_write_text = Path.write_text


def fail_capture_report_write(path, *args, **kwargs):
    if path == Path(os.environ["PYREPAIR_PYTEST_REPORT"]):
        raise OSError("simulated capture report write failure")
    return _write_text(path, *args, **kwargs)


Path.write_text = fail_capture_report_write
""",
        encoding="utf-8",
    )
    report_path = repo / ".pyrepair" / "internal" / "pytest-report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "version": 1,
                "exit_code": 1,
                "failures": [
                    {
                        "node_id": "test_stale.py::test_stale_failure",
                        "phase": "call",
                        "outcome": "failed",
                        "exception_type": "AssertionError",
                        "summary": "stale failure",
                        "traceback": "E AssertionError: stale failure",
                        "duration_ms": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    real_unlink = Path.unlink

    def fail_capture_report_cleanup(path, *args, **kwargs):
        if path == report_path:
            raise OSError("simulated stale report cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_capture_report_cleanup)

    result = PytestRunner(5).run(repo)

    stale_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert stale_report["failures"][0]["node_id"] == "test_stale.py::test_stale_failure"
    assert result.exit_code == 1
    assert result.capture_source == "text"
    assert [failure.node_id for failure in result.failures] == [
        "test_current.py::test_current_failure"
    ]


def test_runner_plugin_is_not_shadowed_by_candidate_pyrepair_package(tmp_path):
    repo = tmp_path / "candidate"
    candidate_package = repo / "pyrepair"
    candidate_package.mkdir(parents=True)
    (candidate_package / "__init__.py").write_text(
        "raise RuntimeError('candidate pyrepair package was imported')\n",
        encoding="utf-8",
    )
    (repo / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n", encoding="utf-8")
    (repo / "test_current.py").write_text(
        "def test_current_failure():\n    assert False, 'current failure'\n",
        encoding="utf-8",
    )

    result = PytestRunner(5).run(repo)

    assert result.exit_code == 1
    assert result.capture_source == "plugin"
    assert [failure.node_id for failure in result.failures] == [
        "test_current.py::test_current_failure"
    ]


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
    assert captured["command"][-2:] == ["-p", "_pyrepair_agent_internal.pytest_plugin"]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["env"]["PYREPAIR_PYTEST_REPORT"] == str(
        tmp_path / ".pyrepair" / "internal" / "pytest-report.json"
    )
    assert captured["kwargs"]["shell"] is False
