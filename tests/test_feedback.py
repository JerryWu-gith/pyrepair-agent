from pyrepair.feedback import (
    MAX_FEEDBACK_DIFF_CHARS,
    MAX_REVIEW_FINDINGS,
    MAX_TEST_OUTPUT_CHARS,
    FeedbackBuilder,
)
from pyrepair.models import (
    FileChange,
    PatchCheck,
    PatchSnapshot,
    PytestFailure,
    ReviewResult,
    VerificationResult,
)
from pyrepair.models import TestRun as PytestRun


def long_snapshot() -> PatchSnapshot:
    diff = "diff --git a/src/app.py b/src/app.py\n" + ("+x\n" * 4000)
    change = FileChange("src/app.py", "old\n", "new\n", diff, 4000, 1)
    return PatchSnapshot((change,))


def failed_verification(summary: str) -> VerificationResult:
    long_output = "prefix\n" + ("detail " * 1000) + summary
    failure = PytestFailure(
        "tests/test_app.py::test_add",
        "call",
        "failed",
        "AssertionError",
        summary,
        "traceback: " + summary,
        1,
    )
    run = PytestRun(
        ("python", "-m", "pytest"),
        1,
        long_output,
        "",
        1,
        failures=(failure,),
        capture_source="plugin",
    )
    check = PatchCheck(True, (), ("src/app.py",), 1, 1)
    return VerificationResult(False, False, (), check, target_run=run)


def test_feedback_contains_patch_policy_review_and_test_evidence():
    findings = tuple(f"finding-{index}" for index in range(7))

    feedback = FeedbackBuilder().build(
        attempt=1,
        outcome="verification_failed",
        snapshot=long_snapshot(),
        patch_check=PatchCheck(True, (), ("src/app.py",), 1, 1),
        review=ReviewResult(False, "high", findings, "reject"),
        verification=failed_verification("new assertion"),
    )

    assert feedback.changed_files == ("src/app.py",)
    assert "src/app.py" in feedback.candidate_diff
    assert feedback.review_findings == findings[:MAX_REVIEW_FINDINGS]
    assert feedback.target_failure is not None
    assert feedback.target_failure.summary == "new assertion"
    assert len(feedback.candidate_diff) <= MAX_FEEDBACK_DIFF_CHARS
    assert len(feedback.target_failure.output_tail) <= MAX_TEST_OUTPUT_CHARS
    assert feedback.truncated is True


def test_feedback_maps_policy_and_loop_outcomes_to_specific_next_focus():
    empty = PatchSnapshot(())
    policy = FeedbackBuilder().build(
        attempt=1,
        outcome="policy_rejected",
        snapshot=empty,
        patch_check=PatchCheck(False, ("protected_test_path",), (), 0, 0),
    )
    loop = FeedbackBuilder().build(
        attempt=2,
        outcome="repeated_tool_call",
        snapshot=empty,
        patch_check=PatchCheck(True, (), (), 0, 0),
    )

    assert "policy" in policy.next_focus.lower()
    assert "strategy" in loop.next_focus.lower()
