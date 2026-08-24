from __future__ import annotations

from pathlib import Path

from .models import PatchSnapshot, VerificationResult
from .policy import PatchPolicyGate
from .pytest_parser import extract_failed_node_ids
from .testing import TestRunner


class Verifier:
    def __init__(self, runner: TestRunner, policy: PatchPolicyGate) -> None:
        self.runner = runner
        self.policy = policy

    def verify(
        self,
        repo: Path,
        target_node_id: str,
        baseline_failures: set[str],
        snapshot: PatchSnapshot,
    ) -> VerificationResult:
        target = self.runner.run(repo, target_node_id)
        target_passed = (
            target.exit_code == 0 and not target.timed_out and target.launch_error is None
        )
        if not target_passed:
            return VerificationResult(
                target_passed=False,
                full_suite_passed=False,
                regression_failures=(),
                patch_check=self.policy.check(snapshot),  #  复查规则
                target_run=target,
                full_run=None,
            )

        full = self.runner.run(repo)
        full_text = "\n".join(part for part in (full.stdout, full.stderr) if part)  # 拼接全部失败
        current_failures = extract_failed_node_ids(full_text)  # 提取全部失败node_id
        regressions = tuple(sorted(current_failures - baseline_failures))  # 修复后现在挂的测试 - 修复前本来就挂的测试 = 回归
        full_suite_passed = (
            full.exit_code == 0 and not full.timed_out and full.launch_error is None
        )
        return VerificationResult(
            target_passed=True,
            full_suite_passed=full_suite_passed,
            regression_failures=regressions,
            patch_check=self.policy.check(snapshot),
            target_run=target,
            full_run=full,
        )
