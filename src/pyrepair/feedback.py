from __future__ import annotations

from dataclasses import dataclass

from .models import PatchCheck, PatchSnapshot, ReviewResult, TestRun, VerificationResult

MAX_FEEDBACK_DIFF_CHARS = 6_000
MAX_TEST_OUTPUT_CHARS = 4_000
MAX_REVIEW_FINDINGS = 5


@dataclass(frozen=True)
class TestFailureEvidence:
    node_id: str | None
    exit_code: int | None
    summary: str
    output_tail: str
    timed_out: bool


@dataclass(frozen=True)
class AttemptFeedback:
    attempt: int
    outcome: str
    changed_files: tuple[str, ...]
    candidate_diff: str
    policy_violations: tuple[str, ...]
    review_findings: tuple[str, ...]
    target_failure: TestFailureEvidence | None
    regression_failures: tuple[str, ...]
    next_focus: str
    truncated: bool = False


class FeedbackBuilder:
    def build(
        self,
        *,
        attempt: int,
        outcome: str,
        snapshot: PatchSnapshot,
        patch_check: PatchCheck,
        review: ReviewResult | None = None,
        verification: VerificationResult | None = None,
    ) -> AttemptFeedback:
        candidate_diff, diff_truncated = _truncate_middle(
            snapshot.text,
            MAX_FEEDBACK_DIFF_CHARS,
        )
        raw_findings = review.findings if review is not None else ()
        if review is not None and not review.approved and not raw_findings and review.reason:
            raw_findings = (review.reason,)
        review_findings = tuple(raw_findings[:MAX_REVIEW_FINDINGS])
        findings_truncated = len(raw_findings) > MAX_REVIEW_FINDINGS
        target_failure, test_truncated = _target_failure(verification)
        regressions = verification.regression_failures if verification is not None else ()
        next_focus = _next_focus(
            outcome,
            patch_check.violations,
            review_findings,
            target_failure,
            regressions,
        )
        return AttemptFeedback(
            attempt=attempt,
            outcome=outcome,
            changed_files=tuple(sorted(patch_check.changed_files)),
            candidate_diff=candidate_diff,
            policy_violations=tuple(patch_check.violations),
            review_findings=review_findings,
            target_failure=target_failure,
            regression_failures=tuple(regressions),
            next_focus=next_focus,
            truncated=diff_truncated or findings_truncated or test_truncated,
        )


def _target_failure(
    verification: VerificationResult | None,
) -> tuple[TestFailureEvidence | None, bool]:
    if (
        verification is None
        or verification.target_passed
        or verification.target_run is None
    ):
        return None, False
    run = verification.target_run
    failure = run.failures[0] if run.failures else None
    output = _test_output(run, failure.traceback if failure is not None else "")
    truncated = len(output) > MAX_TEST_OUTPUT_CHARS
    output_tail = output[-MAX_TEST_OUTPUT_CHARS:]
    if failure is not None:
        node_id = failure.node_id
        summary = failure.summary
    else:
        node_id = None
        summary = _fallback_summary(run)
    return (
        TestFailureEvidence(
            node_id=node_id,
            exit_code=run.exit_code,
            summary=summary,
            output_tail=output_tail,
            timed_out=run.timed_out,
        ),
        truncated,
    )


def _test_output(run: TestRun, fallback: str) -> str:
    parts = [item for item in (run.stdout, run.stderr) if item]
    return "\n".join(parts) or fallback


def _fallback_summary(run: TestRun) -> str:
    if run.timed_out:
        return "Target test timed out."
    if run.launch_error:
        return "Target test could not be launched."
    return "Target test failed without structured failure details."


def _truncate_middle(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = "\n[TRUNCATED]\n"
    available = limit - len(marker)
    head_chars = available // 2
    tail_chars = available - head_chars
    return text[:head_chars] + marker + text[-tail_chars:], True


def _next_focus(
    outcome: str,
    violations: tuple[str, ...],
    findings: tuple[str, ...],
    target_failure: TestFailureEvidence | None,
    regressions: tuple[str, ...],
) -> str:
    if outcome == "no_patch_generated":
        return "Collect new source evidence before attempting another edit."
    if outcome == "policy_rejected":
        detail = violations[0] if violations else "the rejected path or change"
        return f"Avoid the policy violation and redesign the patch: {detail}"
    if outcome == "review_rejected":
        detail = findings[0] if findings else "the review objection"
        return f"Address the independent review finding: {detail}"
    if outcome == "verification_failed" and target_failure is not None:
        return "Use the new target-test traceback and assertion evidence to revise the root cause."
    if regressions:
        return "Narrow the patch scope and preserve behavior covered by the regression failures."
    if outcome in {
        "repeated_tool_call",
        "repeated_tool_error",
        "no_progress",
        "max_model_turns_exceeded",
    }:
        return "Change search strategy and gather different evidence before editing again."
    if outcome == "success":
        return "No further repair attempt is required."
    return "Use the recorded patch and gate evidence to choose a different next action."
