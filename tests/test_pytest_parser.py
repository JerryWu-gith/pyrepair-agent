from pathlib import Path
from typing import Literal

import pytest

from pyrepair.models import PytestFailure
from pyrepair.models import TestRun as PytestRun
from pyrepair.pytest_parser import (
    PytestParser,
    extract_failed_node_ids,
    parse_text_failures,
    select_primary_failure,
)

OUTPUTS = Path(__file__).parent / "fixtures" / "pytest_outputs"


def make_run(text: str) -> PytestRun:
    return PytestRun(
        ("python", "-m", "pytest"),
        1,
        text,
        "",
        12,
        failures=parse_text_failures(text),
        capture_source="text",
    )


def read_output(name: str) -> str:
    return (OUTPUTS / name).read_text(encoding="utf-8")


def test_parse_first_failed_node_exception_and_summary():
    report = PytestParser().parse(make_run(read_output("exception.txt")))

    assert report.node_id == "tests/test_account.py::test_withdraw_rejects_large_amount"
    assert report.exception_type == "ValueError"
    assert report.summary == "insufficient funds"
    assert report.parseable is True


def test_parse_keeps_related_python_paths_without_duplicates():
    report = PytestParser().parse(make_run(read_output("assertion.txt")))

    assert report.related_files == ("tests/test_account.py", "account/service.py")
    assert "E   assert 30 == 20" in report.traceback


def test_unparseable_output_is_explicit_and_preserves_raw_text():
    raw = read_output("unparseable.txt")

    report = PytestParser().parse(make_run(raw))

    assert report.parseable is False
    assert report.node_id is None
    assert report.traceback.strip() == raw.strip()


def test_extract_failed_node_ids_returns_every_unique_failure():
    failures = extract_failed_node_ids(read_output("exception.txt"))

    assert failures == {
        "tests/test_account.py::test_withdraw_rejects_large_amount",
        "tests/test_profile.py::test_profile_name",
    }


@pytest.mark.parametrize(
    "line",
    [
        "FAILED tests/test_a.py::test_x - AssertionError: boom",
        "FAILED tests/test_a.py::test_x",
        "ERROR tests/test_a.py::test_x",
        "tests/test_a.py::test_x FAILED",
    ],
)
def test_text_fallback_accepts_pytest_8_and_9_shapes(line):
    assert parse_text_failures(line)[0].node_id == "tests/test_a.py::test_x"


@pytest.mark.parametrize(
    "text",
    ["FAILED malformed", "ERROR malformed", "malformed::node FAILED", "not a pytest summary"],
)
def test_text_fallback_rejects_unrecognized_summary_text(text):
    assert parse_text_failures(text) == ()


def make_failure(
    node_id: str, phase: Literal["setup", "call", "teardown", "collection"]
) -> PytestFailure:
    return PytestFailure(
        node_id,
        phase,
        "failed",
        "AssertionError",
        "boom",
        "E AssertionError: boom",
        1,
    )


def test_primary_failure_prefers_call_then_setup_then_collection():
    failures = (
        make_failure("tests/test_a.py::test_collect", "collection"),
        make_failure("tests/test_a.py::test_setup", "setup"),
        make_failure("tests/test_a.py::test_call", "call"),
    )

    assert select_primary_failure(failures).phase == "call"
    assert select_primary_failure(failures, "tests/test_a.py::test_setup").phase == "setup"


def test_text_fallback_normalizes_parameterized_node_and_extracts_traceback():
    failure = parse_text_failures(read_output("parameterized.txt"))[0]

    assert failure.node_id == "tests/test_params.py::test_total[windows-path]"
    assert failure.exception_type == "AssertionError"
    assert failure.summary == "assert 1 == 2"
    assert "tests/test_params.py:8" in failure.traceback


def test_text_fallback_extracts_exception_from_pytest9_summary_without_suffix():
    failure = parse_text_failures(read_output("pytest9_failed_without_suffix.txt"))[0]

    assert failure.node_id == "tests/test_a.py::test_boom"
    assert failure.exception_type == "AssertionError"
    assert failure.summary == "boom"


def test_text_fallback_keeps_each_pytest9_failure_traceback_independent():
    text = """\
_______________________________ test_first _______________________________
tests/test_many.py:4: in test_first
    raise AssertionError("first failure")
E   AssertionError: first failure
_______________________________ test_second ______________________________
tests/test_many.py:9: in test_second
    raise ValueError("second failure")
E   ValueError: second failure
FAILED tests/test_many.py::test_first
FAILED tests/test_many.py::test_second
"""

    first, second = parse_text_failures(text)

    assert (first.exception_type, first.summary) == ("AssertionError", "first failure")
    assert "test_second" not in first.traceback
    assert (second.exception_type, second.summary) == ("ValueError", "second failure")
    assert "tests/test_many.py:9" in second.traceback
    assert "test_first" not in second.traceback


def test_text_fallback_marks_setup_errors_and_parser_uses_structured_failure():
    failure = parse_text_failures(read_output("setup_error.txt"))[0]
    run = PytestRun(
        ("python", "-m", "pytest"),
        1,
        read_output("setup_error.txt"),
        "",
        12,
        failures=(failure,),
    )
    report = PytestParser().parse(run, "tests/test_setup.py::test_uses_database")

    assert failure.phase == "setup"
    assert failure.exception_type == "RuntimeError"
    assert report.node_id == "tests/test_setup.py::test_uses_database"
    assert report.parseable is True


def test_parser_selects_structured_failure_by_preferred_node_id():
    failures = (
        make_failure("tests/test_a.py::test_a", "call"),
        make_failure("tests/test_b.py::test_b", "setup"),
    )
    run = PytestRun(("python", "-m", "pytest"), 1, "raw", "", 12, failures=failures)

    report = PytestParser().parse(run, "tests/test_b.py::test_b")

    assert report.node_id == "tests/test_b.py::test_b"
    assert report.exception_type == "AssertionError"
    assert report.parseable is True
