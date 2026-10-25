from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .context_builder import ContextBuilder
from .deepseek import DeepSeekError
from .feedback import AttemptFeedback, FeedbackBuilder
from .models import (
    AgentRun,
    FailureReport,
    RepairRequest,
    ReviewResult,
    RunResult,
    VerificationResult,
)
from .policy import PatchPolicyGate
from .pytest_parser import PytestParser
from .recorder import RunRecorder
from .testing import TestExecutor
from .tools import ToolRegistry
from .verifier import Verifier
from .workspace import WorkspaceManager, WorkspaceSession


class CoordinatorError(RuntimeError):
    def __init__(self, message: str, artifact_dir: Path) -> None:
        super().__init__(message)
        self.artifact_dir = artifact_dir


class RepairCoordinator:
    def __init__(
        self,
        workspaces: WorkspaceManager,
        runner: TestExecutor,
        parser: PytestParser,
        registry_factory: Callable[[WorkspaceSession, str], ToolRegistry],
        agent_factory: Callable[[ToolRegistry], Any],
        context_builder: ContextBuilder,
        feedback_builder: FeedbackBuilder,
        policy: PatchPolicyGate,
        reviewer_factory: Callable[[], Any],
        verifier: Verifier,
        recorder_factory: Callable[[Path], RunRecorder],
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.runner = runner
        self.parser = parser
        self.registry_factory = registry_factory
        self.agent_factory = agent_factory
        self.context_builder = context_builder
        self.feedback_builder = feedback_builder
        self.policy = policy
        self.reviewer_factory = reviewer_factory
        self.verifier = verifier
        self.recorder_factory = recorder_factory
        self.progress = progress or (lambda stage: None)

    def run(self, request: RepairRequest) -> RunResult:
        session = self.workspaces.create(request.repo)  # 建沙箱：baseline + working
        recorder: RunRecorder | None = None
        failure_report: FailureReport | None = None
        attempt_records: list[dict[str, Any]] = []
        try:
            recorder = self.recorder_factory(request.repo)  # 建记录器
            self._emit("baseline")
            baseline = self.runner.run(session.working, request.test_target)  #返回Testrun
            recorder.append_pytest("BASELINE", baseline)
            recorder.append_event(
                {
                    "type": "baseline",
                    "exit_code": baseline.exit_code,
                    "duration_ms": baseline.duration_ms,
                    "capture_source": baseline.capture_source,
                    "failure_count": len(baseline.failures),
                }
            )
            if baseline.timed_out:
                result = self._finish(
                    recorder,
                    status="failed",
                    attempt_count=0,
                    failure_reason="baseline_timeout",
                    failure_report=None,
                    attempt_records=attempt_records,
                )
                raise CoordinatorError("基线 pytest 执行超时", result.artifact_dir)
            if baseline.launch_error:
                result = self._finish(
                    recorder,
                    status="failed",
                    attempt_count=0,
                    failure_reason="baseline_launch_error",
                    failure_report=None,
                    attempt_records=attempt_records,
                )
                raise CoordinatorError(
                    f"基线 pytest 无法启动：{baseline.launch_error}",
                    result.artifact_dir,
                )

            failure_report = self.parser.parse(baseline, request.test_target)  #TestRun → FailureReport
            if baseline.exit_code == 0:
                return self._finish(
                    recorder,
                    status="failed",
                    attempt_count=0,
                    failure_reason="tests_already_pass",
                    failure_report=failure_report,
                    attempt_records=attempt_records,
                )
            if not failure_report.parseable or not failure_report.node_id:
                return self._finish(
                    recorder,
                    status="failed",
                    attempt_count=0,
                    failure_reason="unparseable_pytest_output",
                    failure_report=failure_report,
                    attempt_records=attempt_records,
                )
            if request.dry_run:
                return self._finish(
                    recorder,
                    status="dry_run",
                    attempt_count=0,
                    failure_reason=None,
                    failure_report=failure_report,
                    attempt_records=attempt_records,
                )

            context_bundle = self.context_builder.build(session.baseline, failure_report)
            recorder.append_event(
                {
                    "type": "context_built",
                    "total_chars": context_bundle.total_chars,
                    "snippet_count": len(context_bundle.snippets),
                    "selected_files": sorted(
                        {item.path for item in context_bundle.snippets}
                    ),
                    "truncated": context_bundle.truncated,
                }
            )
            baseline_failures = {item.node_id for item in baseline.failures}
            baseline_failures.add(failure_report.node_id)
            feedbacks: list[AttemptFeedback] = []

            for attempt in range(1, request.max_attempts + 1):
                self._emit(f"attempt:{attempt}")
                session.restore_working_from_baseline()   #一键重置工作区，把 agent 的沙箱（working）删掉重建回干净的基线状态（baseline）
                registry = self.registry_factory(session, failure_report.node_id)  #重置工具
                agent_run = self.agent_factory(registry).run(
                    failure_report,
                    tuple(feedbacks),
                    context=context_bundle,
                    attempt=attempt,
                    max_attempts=request.max_attempts,
                )
                self._record_agent_turns(recorder, attempt, agent_run) # 记录 token 用量
                snapshot = session.snapshot()     # agent 改完 → 对比 baseline/working 生成补丁
                check = self.policy.check(snapshot)  # 策略预检
                attempt_record = {
                    "attempt": attempt,
                    "agent_completed": agent_run.completed,
                    "agent_failure_reason": agent_run.failure_reason,
                    "changed_files": list(check.changed_files),
                    "policy_allowed": check.allowed,
                    "policy_violations": list(check.violations),
                }
                status = agent_run.final_status
                attempt_record.update(
                    {
                        "tool_calls_used": status.tool_calls_used if status else 0,
                        "repeated_call_count": status.repeated_call_count if status else 0,
                        "no_progress_steps": status.no_progress_steps if status else 0,
                        "guard_events": list(agent_run.guard_events),
                        "target_test_runs": sum(
                            call.name == "run_target_test"
                            for turn in agent_run.turns
                            for call in turn.tool_calls
                        ),
                    }
                )

                if not snapshot.changes:  # 没生成补丁
                    attempt_record["outcome"] = "no_patch_generated"
                    self._attach_feedback(
                        feedbacks,
                        attempt_record,
                        attempt,
                        snapshot,
                        check,
                    )
                    attempt_records.append(attempt_record)
                    continue
                if not agent_run.completed:
                    reason = agent_run.failure_reason or "agent_incomplete"
                    attempt_record["outcome"] = reason
                    self._attach_feedback(
                        feedbacks,
                        attempt_record,
                        attempt,
                        snapshot,
                        check,
                    )
                    attempt_records.append(attempt_record)
                    continue

                self._emit("policy")
                if not check.allowed:
                    attempt_record["outcome"] = "policy_rejected"
                    self._attach_feedback(
                        feedbacks,
                        attempt_record,
                        attempt,
                        snapshot,
                        check,
                    )
                    attempt_records.append(attempt_record)
                    continue

                self._emit("review")
                reviewer = self.reviewer_factory()
                if context_bundle.task_contract != "":
                    review = reviewer.review(
                        failure_report, snapshot, task_contract=context_bundle.task_contract
                    )
                else:
                    review = reviewer.review(failure_report, snapshot)
                recorder.append_event(
                    {
                        "type": "model_turn",
                        "role": "review",
                        "attempt": attempt,
                        "prompt_tokens": review.prompt_tokens,
                        "completion_tokens": review.completion_tokens,
                    }
                )
                attempt_record["review"] = _review_data(review)
                if not review.approved:
                    attempt_record["outcome"] = "review_rejected"
                    self._attach_feedback(
                        feedbacks,
                        attempt_record,
                        attempt,
                        snapshot,
                        check,
                        review=review,
                    )
                    attempt_records.append(attempt_record)
                    continue

                self._emit("verify")
                verification = self.verifier.verify(
                    session.working,
                    failure_report.node_id,
                    baseline_failures,
                    snapshot,
                )
                if verification.target_run is not None:
                    recorder.append_pytest(f"ATTEMPT {attempt} TARGET", verification.target_run)
                if verification.full_run is not None:
                    recorder.append_pytest(f"ATTEMPT {attempt} FULL", verification.full_run)
                attempt_record.update(_verification_data(verification))
                if verification.passed:
                    attempt_record["outcome"] = "success"
                    self._attach_feedback(
                        feedbacks,
                        attempt_record,
                        attempt,
                        snapshot,
                        check,
                        review=review,
                        verification=verification,
                    )
                    attempt_records.append(attempt_record)
                    recorder.write_patch(snapshot)
                    return self._finish(
                        recorder,
                        status="success",
                        attempt_count=attempt,
                        failure_reason=None,
                        failure_report=failure_report,
                        attempt_records=attempt_records,
                    )

                attempt_record["outcome"] = "verification_failed"
                self._attach_feedback(
                    feedbacks,
                    attempt_record,
                    attempt,
                    snapshot,
                    check,
                    review=review,
                    verification=verification,
                )
                attempt_records.append(attempt_record)

            return self._finish(
                recorder,
                status="failed",
                attempt_count=request.max_attempts,
                failure_reason="max_attempts_exceeded",
                failure_report=failure_report,
                attempt_records=attempt_records,
            )
        except CoordinatorError:
            raise
        except DeepSeekError as exc:
            if recorder is None:
                raise
            result = self._finish(
                recorder,
                status="failed",
                attempt_count=len(attempt_records),
                failure_reason="deepseek_error",
                failure_report=failure_report,
                attempt_records=attempt_records,
            )
            raise CoordinatorError(f"DeepSeek 调用失败：{exc}", result.artifact_dir) from exc
        finally:
            session.cleanup()

    def _emit(self, stage: str) -> None:
        self.progress(stage)

    def _record_agent_turns(
        self,
        recorder: RunRecorder,
        attempt: int,
        agent_run: AgentRun,
    ) -> None:
        for turn_index, turn in enumerate(agent_run.turns, start=1):
            recorder.append_event(
                {
                    "type": "model_turn",
                    "role": "repair",
                    "attempt": attempt,
                    "turn": turn_index,
                    "tool_calls": [call.name for call in turn.tool_calls],
                    "prompt_tokens": turn.prompt_tokens,
                    "completion_tokens": turn.completion_tokens,
                    "stop_reason": turn.stop_reason,
                }
            )

    def _attach_feedback(
        self,
        feedbacks: list[AttemptFeedback],
        attempt_record: dict[str, Any],
        attempt: int,
        snapshot,
        check,
        *,
        review: ReviewResult | None = None,
        verification: VerificationResult | None = None,
    ) -> None:
        feedback = self.feedback_builder.build(
            attempt=attempt,
            outcome=str(attempt_record["outcome"]),
            snapshot=snapshot,
            patch_check=check,
            review=review,
            verification=verification,
        )
        feedbacks.append(feedback)
        attempt_record["feedback"] = asdict(feedback)

    def _finish(
        self,
        recorder: RunRecorder,
        *,
        status: str,
        attempt_count: int,
        failure_reason: str | None,
        failure_report: FailureReport | None,
        attempt_records: list[dict[str, Any]],
    ) -> RunResult:
        report = {
            "status": status,
            "attempt_count": attempt_count,
            "failure_reason": failure_reason,
            "failure": _failure_data(failure_report),
            "attempts": attempt_records,
        }
        recorder.write_report(report)
        recorder.append_event(
            {
                "type": "run_finished",
                "status": status,
                "attempt_count": attempt_count,
                "failure_reason": failure_reason,
            }
        )
        return RunResult(
            status=status,
            attempts=attempt_count,
            artifact_dir=recorder.run_dir,
            failure_reason=failure_reason,
            metadata={"attempts": attempt_records},
        )


def _failure_data(report: FailureReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "node_id": report.node_id,
        "exception_type": report.exception_type,
        "summary": report.summary,
        "related_files": list(report.related_files),
        "parseable": report.parseable,
    }


def _review_data(review: ReviewResult) -> dict[str, Any]:
    return {
        "approved": review.approved,
        "risk": review.risk,
        "findings": list(review.findings),
        "reason": review.reason,
    }


def _verification_data(verification: VerificationResult) -> dict[str, Any]:
    return {
        "target_passed": verification.target_passed,
        "full_suite_passed": verification.full_suite_passed,
        "regression_failures": list(verification.regression_failures),
        "final_policy_allowed": verification.patch_check.allowed,
    }


def _verification_evidence(verification: VerificationResult) -> list[str]:
    evidence: list[str] = []
    if not verification.target_passed:
        evidence.append("target_test_failed")
    if not verification.full_suite_passed:
        evidence.append("full_suite_failed")
    evidence.extend(f"regression:{node_id}" for node_id in verification.regression_failures)
    evidence.extend(verification.patch_check.violations)
    return evidence
