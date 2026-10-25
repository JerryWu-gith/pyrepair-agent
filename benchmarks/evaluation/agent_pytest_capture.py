"""Trusted, bounded Agent diagnostics attached to the ordinary evaluation probe."""

from __future__ import annotations

import re

import pytest

from benchmarks.evaluation import pytest_probe

_failures: dict[tuple[str, str], dict] = {}


def pytest_sessionstart(session):
    _failures.clear()


def _record(report, phase: str) -> None:
    if not report.failed:
        return
    traceback = report.longreprtext
    crash = getattr(report.longrepr, "reprcrash", None)
    summary = getattr(crash, "message", None) or traceback.splitlines()[-1]
    exception_type = getattr(report, "pyrepair_exception_type", None)
    if exception_type is None:
        for line in reversed(traceback.splitlines()):
            match = re.match(r"(?:E\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):", line.strip())
            if match:
                exception_type = match[1]
                break
    node = report.nodeid.replace("\\", "/")
    pair = (node, phase)
    duration = max(0, int(getattr(report, "duration", 0) * 1000))
    if pair in _failures:
        previous = _failures[pair]
        traceback = previous["traceback"] + "\n\n" + traceback
        duration += previous["duration_ms"]
        if previous["exception_type"] != exception_type:
            exception_type = None
    if len(traceback) > 16000:
        traceback = traceback[:7990] + "\n[TRUNCATED]\n" + traceback[-7990:]
    _failures[pair] = {
        "node_id": node,
        "phase": phase,
        "outcome": "failed",
        "exception_type": exception_type,
        "summary": str(summary)[:2000],
        "traceback": traceback,
        "duration_ms": duration,
    }


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_logreport(report):
    # Terminal status formatting may mutate a passed parent into a synthetic
    # "contains N failed subtests" failure. Capture the original report first;
    # real child failures are already recorded with their exception evidence.
    _record(report, report.when)
    yield


def pytest_collectreport(report):
    _record(report, "collection")


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    # The existing probe serializes at trylast, after merging pytest9 subtests.
    pytest_probe._data["failures"] = list(_failures.values())
