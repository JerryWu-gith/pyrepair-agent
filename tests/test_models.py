import pytest

from pyrepair.models import (
    AgentRun,
    FileChange,
    PatchCheck,
    PatchSnapshot,
    PytestFailure,
    VerificationResult,
)
from pyrepair.models import TestRun as PytestRun


def test_test_run_keeps_structured_failures_with_legacy_defaults():
    failure = PytestFailure(
        "tests/test_app.py::test_add",
        "call",
        "failed",
        "AssertionError",
        "assert -1 == 5",
        "E assert -1 == 5",
        7,
    )
    run = PytestRun(
        ("python", "-m", "pytest"),
        1,
        "",
        "",
        10,
        failures=(failure,),
        capture_source="plugin",
    )
    legacy = PytestRun(("python", "-m", "pytest"), 1, "", "", 10)

    assert run.failures == (failure,)
    assert run.capture_source == "plugin"
    assert legacy.failures == ()
    assert legacy.capture_source == "none"


def test_agent_run_keeps_state_fields_optional_for_legacy_callers():
    run = AgentRun(True, ())

    assert run.final_status is None
    assert run.guard_events == ()


def test_patch_snapshot_text_joins_changes_in_order():
    first = FileChange("a.py", "a", "b", "diff-a\n", 1, 1)
    second = FileChange("b.py", "c", "d", "diff-b\n", 1, 1)

    snapshot = PatchSnapshot((first, second))

    assert snapshot.text == "diff-a\ndiff-b\n"


@pytest.mark.parametrize(
    ("target_passed", "full_suite_passed", "regressions", "policy_allowed"),
    [
        (False, True, (), True),
        (True, False, (), True),
        (True, True, ("tests/test_other.py::test_other",), True),
        (True, True, (), False),
    ],
)
def test_verification_result_rejects_any_failed_gate(
    target_passed,
    full_suite_passed,
    regressions,
    policy_allowed,
):
    policy = PatchCheck(policy_allowed, (), (), 0, 0)
    result = VerificationResult(target_passed, full_suite_passed, regressions, policy)

    assert result.passed is False


def test_verification_result_passes_when_every_gate_passes():
    policy = PatchCheck(True, (), ("src/app.py",), 1, 1)
    result = VerificationResult(True, True, (), policy)

    assert result.passed is True
