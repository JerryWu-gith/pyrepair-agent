"""Compatibility import for the isolated pytest capture plugin."""

from _pyrepair_agent_internal.pytest_plugin import (
    _serialize_report,
    pytest_collectreport,
    pytest_runtest_logreport,
    pytest_sessionfinish,
)

__all__ = [
    "_serialize_report",
    "pytest_collectreport",
    "pytest_runtest_logreport",
    "pytest_sessionfinish",
]
