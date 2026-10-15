"""Evaluation-only pytest plugin. Unlike the Agent plugin, records every outcome."""

import json
import os
from pathlib import Path

import pytest

_data = {}


def pytest_sessionstart(session):
    _data.clear()
    _data.update(version=1, finished=False, collected=[], reports=[], collection_errors=[])


def pytest_collection_finish(session):
    _data["collected"] = [item.nodeid.replace("\\", "/") for item in session.items]


def pytest_collectreport(report):
    if report.failed or report.skipped:
        _data["collection_errors"].append({"nodeid": report.nodeid, "outcome": report.outcome})


def pytest_runtest_logreport(report):
    _data["reports"].append(
        {
            "nodeid": report.nodeid.replace("\\", "/"),
            "when": report.when,
            "outcome": report.outcome,
            "wasxfail": hasattr(report, "wasxfail"),
        }
    )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    _data.update(finished=True, exit_code=int(exitstatus))
    Path(os.environ["PYREPAIR_EVAL_PROBE"]).write_text(
        json.dumps(_data, ensure_ascii=False), encoding="utf-8"
    )
