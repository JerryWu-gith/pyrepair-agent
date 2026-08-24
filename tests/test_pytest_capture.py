import json

import pytest

from pyrepair.pytest_capture import CaptureReportError, load_capture_report


def test_load_capture_report_converts_valid_json(tmp_path):
    path = tmp_path / "pytest-report.json"
    path.write_text(
        json.dumps(
            {
                "failures": [
                    {
                        "node_id": "tests/test_app.py::test_add",
                        "phase": "call",
                        "outcome": "failed",
                        "exception_type": "AssertionError",
                        "summary": "assert -1 == 5",
                        "traceback": "E assert -1 == 5",
                        "duration_ms": 7,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_capture_report(path)[0].phase == "call"


@pytest.mark.parametrize(
    "payload",
    ["{", '{"failures": {}}', '{"failures": [{"phase": "unknown"}]}'],
)
def test_load_capture_report_rejects_invalid_payload(tmp_path, payload):
    path = tmp_path / "pytest-report.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(CaptureReportError, match="invalid_pytest_capture_report"):
        load_capture_report(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("node_id", 1),
        ("phase", 1),
        ("outcome", 1),
        ("summary", 1),
        ("traceback", 1),
        ("exception_type", 1),
        ("duration_ms", True),
        ("duration_ms", -1),
    ],
)
def test_load_capture_report_rejects_invalid_failure_fields(tmp_path, field, value):
    failure = {
        "node_id": "tests/test_app.py::test_add",
        "phase": "call",
        "outcome": "failed",
        "exception_type": "AssertionError",
        "summary": "assert -1 == 5",
        "traceback": "E assert -1 == 5",
        "duration_ms": 7,
    }
    failure[field] = value
    path = tmp_path / "pytest-report.json"
    path.write_text(json.dumps({"failures": [failure]}), encoding="utf-8")

    with pytest.raises(CaptureReportError, match="invalid_pytest_capture_report"):
        load_capture_report(path)


def test_load_capture_report_rejects_extra_fields(tmp_path):
    failure = {
        "node_id": "tests/test_app.py::test_add",
        "phase": "call",
        "outcome": "failed",
        "exception_type": None,
        "summary": "assert -1 == 5",
        "traceback": "E assert -1 == 5",
        "duration_ms": 7,
        "extra": "not allowed",
    }
    path = tmp_path / "pytest-report.json"
    path.write_text(json.dumps({"failures": [failure]}), encoding="utf-8")

    with pytest.raises(CaptureReportError, match="invalid_pytest_capture_report"):
        load_capture_report(path)
