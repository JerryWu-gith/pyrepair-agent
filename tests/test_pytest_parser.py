from pathlib import Path

from pyrepair.models import TestRun as PytestRun
from pyrepair.pytest_parser import PytestParser, extract_failed_node_ids

OUTPUTS = Path(__file__).parent / "fixtures" / "pytest_outputs"


def make_run(text: str) -> PytestRun:
    return PytestRun(("python", "-m", "pytest"), 1, text, "", 12)


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
