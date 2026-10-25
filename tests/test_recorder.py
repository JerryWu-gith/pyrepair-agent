import errno
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from pyrepair.models import FileChange, PatchSnapshot, PytestFailure
from pyrepair.models import TestRun as PytestRun
from pyrepair.recorder import RecorderError, RunRecorder


def patch_snapshot() -> PatchSnapshot:
    return PatchSnapshot(
        (
            FileChange(
                "src/app.py",
                "value = 1\n",
                "value = 2\n",
                "--- a/src/app.py\n+++ b/src/app.py\n-value = 1\n+value = 2\n",
                1,
                1,
            ),
        )
    )


def test_recorder_creates_four_artifacts_and_redacts_secrets(tmp_path):
    recorder = RunRecorder(
        tmp_path,
        run_id="20260812T120000Z-test",
        sensitive_values=("sk-secret-value",),
    )
    recorder.write_patch(patch_snapshot())
    recorder.write_report(
        {
            "status": "success",
            "api_key": "sk-secret-value",
            "message": "request used sk-secret-value",
        }
    )
    recorder.append_event(
        {"type": "model", "authorization": "Bearer sk-secret-value"}
    )

    names = {path.name for path in recorder.run_dir.iterdir()}
    combined = "".join(
        path.read_text(encoding="utf-8") for path in recorder.run_dir.iterdir()
    )

    assert names == {"fix.patch", "report.json", "trace.jsonl", "pytest.log"}
    assert "sk-secret-value" not in combined
    assert "[REDACTED]" in combined


def test_recorder_outputs_valid_json_and_jsonl(tmp_path):
    recorder = RunRecorder(tmp_path, run_id="valid-json")
    recorder.write_report({"status": "failed", "artifact": Path("run/fix.patch")})
    recorder.append_event({"type": "start", "attempt": 0})
    recorder.append_event({"type": "finish", "attempt": 1})

    report = json.loads((recorder.run_dir / "report.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (recorder.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert report == {"status": "failed", "artifact": "run/fix.patch"}
    assert [event["type"] for event in events] == ["start", "finish"]


def test_recorder_serializes_dataclasses_and_iterables(tmp_path):
    recorder = RunRecorder(tmp_path, run_id="serialized-values")
    run = PytestRun(
        ("python", "-m", "pytest"),
        1,
        "1 failed",
        "",
        10,
        failures=(
            PytestFailure(
                "tests/test_app.py::test_add",
                "call",
                "failed",
                "AssertionError",
                "boom",
                "E AssertionError: boom",
                1,
            ),
        ),
    )

    recorder.write_report({"run": run, "values": {3, 1}, "items": ("item",)})

    report = json.loads((recorder.run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["run"]["failures"][0]["node_id"] == "tests/test_app.py::test_add"
    assert report["values"] == [1, 3]
    assert report["items"] == ["item"]


def test_recorder_appends_named_pytest_sections(tmp_path):
    recorder = RunRecorder(tmp_path, run_id="pytest-log")
    baseline = PytestRun(
        ("python", "-m", "pytest"),
        1,
        "FAILED tests/test_app.py::test_add",
        "",
        120,
    )
    target = PytestRun(("python", "-m", "pytest"), 0, "1 passed", "", 40)

    recorder.append_pytest("BASELINE", baseline)
    recorder.append_pytest("TARGET", target)

    log = (recorder.run_dir / "pytest.log").read_text(encoding="utf-8")
    assert "===== BASELINE =====" in log
    assert "exit_code: 1" in log
    assert "FAILED tests/test_app.py::test_add" in log
    assert "===== TARGET =====" in log
    assert "1 passed" in log


def test_recorder_includes_pytest_capture_metadata(tmp_path):
    recorder = RunRecorder(tmp_path, run_id="pytest-capture")
    baseline = PytestRun(
        ("python", "-m", "pytest"),
        1,
        "1 failed",
        "",
        120,
        failures=(
            PytestFailure(
                "tests/test_app.py::test_add",
                "call",
                "failed",
                "AssertionError",
                "boom",
                "full traceback",
                1,
            ),
        ),
        capture_source="plugin",
    )

    recorder.append_pytest("BASELINE", baseline)

    log = (recorder.run_dir / "pytest.log").read_text(encoding="utf-8")
    assert "capture_source: plugin" in log
    assert "failure_count: 1" in log


def test_failed_run_can_keep_empty_patch_file(tmp_path):
    recorder = RunRecorder(tmp_path, run_id="failed-run")
    recorder.write_report({"status": "failed", "failure_reason": "max_attempts_exceeded"})

    assert (recorder.run_dir / "fix.patch").read_text(encoding="utf-8") == ""
    report = json.loads((recorder.run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"


def test_recorder_does_not_double_windows_newlines_in_patch(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path, run_id="windows-newlines")
    snapshot = PatchSnapshot(
        (
            FileChange(
                "src/app.py",
                "value = 1\r\n",
                "value = 2\r\n",
                "--- a/src/app.py\r\n+++ b/src/app.py\r\n-value = 1\r\n+value = 2\r\n",
                1,
                1,
            ),
        )
    )

    recorder.write_patch(snapshot)

    raw_patch = (recorder.run_dir / "fix.patch").read_bytes()
    assert b"\r\r\n" not in raw_patch
    assert raw_patch.count(b"\r\n") == 4


@pytest.mark.parametrize("run_id", ["../escape", "folder/run", "folder\\run", ""])
def test_recorder_rejects_unsafe_run_id(tmp_path, run_id):
    with pytest.raises(RecorderError, match="run-id"):
        RunRecorder(tmp_path, run_id=run_id)


def windows_permission_error(code):
    error = PermissionError(errno.EACCES, "file temporarily unavailable")
    error.winerror = code
    return error


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_recorder_retries_transient_replace_without_losing_or_duplicating_events(
    tmp_path, monkeypatch, winerror
):
    import time

    recorder = RunRecorder(tmp_path, run_id="transient-replace")
    recorder.append_event({"type": "before"})
    trace = recorder.run_dir / "trace.jsonl"
    before = trace.read_bytes()
    original_replace = Path.replace
    attempts = []
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)

    def temporarily_locked(path, target):
        attempts.append(path)
        if len(attempts) <= 2:
            assert trace.read_bytes() == before
            raise windows_permission_error(winerror)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", temporarily_locked)
    recorder.append_event({"type": "after"})

    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert events == [{"type": "before"}, {"type": "after"}]
    assert len(attempts) == 3
    assert [call.args[0] for call in sleep.call_args_list] == [0.05, 0.1]
    assert not trace.with_suffix(".jsonl.tmp").exists()


def test_recorder_replace_retry_is_bounded_and_preserves_original_on_failure(
    tmp_path, monkeypatch
):
    import time

    recorder = RunRecorder(tmp_path, run_id="permanent-replace")
    trace = recorder.run_dir / "trace.jsonl"
    before = trace.read_bytes()
    error = windows_permission_error(5)
    replace = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(time, "sleep", sleep)

    with pytest.raises(RecorderError) as caught:
        recorder.append_event({"type": "not-committed"})

    assert replace.call_count == 5
    assert [call.args[0] for call in sleep.call_args_list] == [0.05, 0.1, 0.2, 0.4]
    assert caught.value.__cause__ is error
    assert trace.read_bytes() == before
    assert trace.with_suffix(".jsonl.tmp").exists()


@pytest.mark.parametrize(
    "error", [PermissionError(errno.EACCES, "denied"), OSError(errno.ENOSPC, "full")]
)
def test_recorder_does_not_retry_unrelated_replace_errors(tmp_path, monkeypatch, error):
    import time

    recorder = RunRecorder(tmp_path, run_id="unrelated-error")
    trace = recorder.run_dir / "trace.jsonl"
    before = trace.read_bytes()
    replace = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(time, "sleep", sleep)

    with pytest.raises(RecorderError) as caught:
        recorder.append_event({"type": "not-committed"})

    assert replace.call_count == 1
    assert sleep.call_count == 0
    assert caught.value.__cause__ is error
    assert trace.read_bytes() == before


def test_recorder_does_not_retry_temporary_file_write_failure(tmp_path, monkeypatch):
    import time

    recorder = RunRecorder(tmp_path, run_id="temporary-write-error")
    trace = recorder.run_dir / "trace.jsonl"
    before = trace.read_bytes()
    write = Mock(side_effect=windows_permission_error(5))
    replace = Mock()
    sleep = Mock()
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(time, "sleep", sleep)

    with pytest.raises(RecorderError):
        recorder.append_event({"type": "not-committed"})

    assert write.call_count == 1
    assert replace.call_count == 0
    assert sleep.call_count == 0
    assert trace.read_bytes() == before
