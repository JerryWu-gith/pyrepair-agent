"""Evaluation-only pytest plugin. Unlike the Agent plugin, records every outcome."""

import json
import os
from pathlib import Path

import pytest

try:
    # Built into the pinned pytest 9 runtime; keep ordinary pytest 8 probes usable.
    from _pytest.subtests import SubtestReport
except ImportError:
    _subtest_types = ()
else:
    _subtest_types = (SubtestReport,)

_data = {}


def pytest_sessionstart(session):
    _data.clear()
    _data.update(version=1, finished=False, collected=[], reports=[], collection_errors=[])


def pytest_collection_finish(session):
    _data["collected"] = [item.nodeid.replace("\\", "/") for item in session.items]


def pytest_collectreport(report):
    if report.failed or report.skipped:
        _data["collection_errors"].append({"nodeid": report.nodeid, "outcome": report.outcome})


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is not None:
        report.pyrepair_exception_type = call.excinfo.type.__name__


def pytest_runtest_logreport(report):
    # Subtests share their parent's nodeid/when, but are not duplicate main phases.
    records = (
        _data.setdefault("subtests", []) if isinstance(report, _subtest_types) else _data["reports"]
    )
    records.append(
        {
            "nodeid": report.nodeid.replace("\\", "/"),
            "when": report.when,
            "outcome": report.outcome,
            "wasxfail": hasattr(report, "wasxfail"),
            **(
                {"exception_type": report.pyrepair_exception_type}
                if hasattr(report, "pyrepair_exception_type")
                else {}
            ),
        }
    )


def _merge_subtest_outcomes():
    by_node = {}
    for child in _data.get("subtests", []):
        by_node.setdefault(child["nodeid"], []).append(child)
    for row in _data["reports"]:
        if row["when"] != "call":
            continue
        children = by_node.get(row["nodeid"], [])
        if any(c["outcome"] == "skipped" or c["wasxfail"] for c in children):
            # A skipped/xfail child must not be accepted as a fully exercised node.
            row["outcome"] = "skipped"
            row.pop("exception_type", None)
        elif failures := [c for c in children if c["outcome"] == "failed"]:
            exception_types = {c.get("exception_type") for c in failures}
            if row["outcome"] == "failed" and "exception_type" in row:
                exception_types.add(row["exception_type"])
            row["outcome"] = "failed"
            row.pop("exception_type", None)
            # Mixed/unknown exceptions cannot masquerade as assertion-only F2P.
            if exception_types == {"AssertionError"}:
                row["exception_type"] = "AssertionError"


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    _merge_subtest_outcomes()
    _data.update(finished=True, exit_code=int(exitstatus))
    Path(os.environ["PYREPAIR_EVAL_PROBE"]).write_text(
        json.dumps(_data, ensure_ascii=False), encoding="utf-8"
    )
