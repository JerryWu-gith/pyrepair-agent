from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PytestFailure


class CaptureReportError(RuntimeError):
    pass


_FAILURE_FIELDS = {
    "node_id",
    "phase",
    "outcome",
    "exception_type",
    "summary",
    "traceback",
    "duration_ms",
}
_PHASES = {"setup", "call", "teardown", "collection"}


def load_capture_report(path: Path) -> tuple[PytestFailure, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"failures"}:
            raise TypeError("report must contain only failures")
        items = payload["failures"]
        if not isinstance(items, list):
            raise TypeError("failures must be a list")
        return tuple(_parse_failure(item) for item in items)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CaptureReportError("invalid_pytest_capture_report") from exc


def _parse_failure(item: Any) -> PytestFailure:
    if not isinstance(item, dict) or set(item) != _FAILURE_FIELDS:
        raise TypeError("failure fields are invalid")

    node_id = item["node_id"]
    phase = item["phase"]
    outcome = item["outcome"]
    exception_type = item["exception_type"]
    summary = item["summary"]
    traceback = item["traceback"]
    duration_ms = item["duration_ms"]

    if not all(isinstance(value, str) for value in (node_id, phase, outcome, summary, traceback)):
        raise TypeError("failure string fields are invalid")
    if phase not in _PHASES:
        raise ValueError("failure phase is invalid")
    if exception_type is not None and not isinstance(exception_type, str):
        raise TypeError("exception type is invalid")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
        raise ValueError("failure duration is invalid")

    return PytestFailure(
        node_id,
        phase,
        outcome,
        exception_type,
        summary,
        traceback,
        duration_ms,
    )
