from pathlib import Path

from pyrepair.pytest_parser import PytestParser
from pyrepair.testing import TestRunner as PytestRunner

EXAMPLE = Path(__file__).parents[1] / "examples" / "buggy_bank"


def test_buggy_bank_has_one_parseable_withdraw_failure():
    run = PytestRunner(timeout_seconds=10).run(EXAMPLE)
    report = PytestParser().parse(run)

    assert run.exit_code == 1
    assert report.parseable is True
    assert report.node_id == "tests/test_bank.py::test_withdraw_reduces_balance"
