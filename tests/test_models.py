import pytest

from pyrepair.models import FileChange, PatchCheck, PatchSnapshot, VerificationResult


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
