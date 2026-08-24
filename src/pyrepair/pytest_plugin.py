from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

_FAILURES: list[dict[str, object]] = []
_EXCEPTION_LINE = re.compile(r"^\s*(?:E\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):\s+.+$", re.MULTILINE)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.failed:
        _FAILURES.append(_serialize_report(report, report.when))


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.failed:
        _FAILURES.append(_serialize_report(report, "collection"))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session
    destination = os.environ.get("PYREPAIR_PYTEST_REPORT")
    if not destination:
        return
    try:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"version": 1, "exit_code": int(exitstatus), "failures": _FAILURES},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def _serialize_report(report: pytest.TestReport | pytest.CollectReport, phase: str) -> dict[str, object]:
    traceback = str(getattr(report, "longreprtext", ""))[-12000:]
    lines = [line.strip() for line in traceback.splitlines() if line.strip()]
    summary = lines[-1][-1000:] if lines else ""
    match = _EXCEPTION_LINE.search(traceback)
    duration_seconds = getattr(report, "duration", 0.0)
    duration_ms = max(0, int(float(duration_seconds) * 1000))
    return {
        "node_id": str(report.nodeid),
        "phase": phase,
        "outcome": str(report.outcome),
        "exception_type": match.group(1) if match else None,
        "summary": summary,
        "traceback": traceback,
        "duration_ms": duration_ms,
    }
