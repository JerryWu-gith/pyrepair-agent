"""Opt-in Review label evidence from actual pytest exceptions, not log text."""

import json
import os
from pathlib import Path

import pytest

_failures = []


def pytest_sessionstart(session):
    _failures.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        error = call.excinfo.value if call.excinfo is not None else None
        _failures.append(
            {
                "nodeid": report.nodeid.replace("\\", "/"),
                "phase": call.when,
                "is_assertion": isinstance(error, AssertionError),
                "exception_type": type(error).__name__ if error is not None else None,
            }
        )


def pytest_sessionfinish(session, exitstatus):
    target = Path(os.environ["PYREPAIR_EVAL_PROBE"]).with_suffix(".assertions.json")
    target.write_text(
        json.dumps(
            {"version": 1, "finished": True, "exit_code": int(exitstatus), "failures": _failures}
        ),
        encoding="utf-8",
    )
