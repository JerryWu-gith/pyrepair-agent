from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class RepairRequest:
    repo: Path
    test_target: str | None = None
    model: str = "deepseek-v4-flash"
    max_attempts: int = 3
    dry_run: bool = False
    verbose: bool = False


@dataclass(frozen=True)
class TestRun:
    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    launch_error: str | None = None


@dataclass(frozen=True)
class FailureReport:
    node_id: str | None
    exception_type: str | None
    traceback: str
    summary: str
    related_files: tuple[str, ...] = ()
    parseable: bool = True


@dataclass(frozen=True)
class FileChange:
    path: str
    old_text: str
    new_text: str
    diff: str
    added_lines: int
    deleted_lines: int


@dataclass(frozen=True)
class PatchSnapshot:
    changes: tuple[FileChange, ...]

    @property
    def text(self) -> str:
        return "".join(change.diff for change in self.changes)


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    content: str
    reasoning_content: str | None
    tool_calls: tuple[ToolCallRequest, ...]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stop_reason: str | None = None


@dataclass(frozen=True)
class AgentRun:
    completed: bool
    turns: tuple[ModelTurn, ...]
    failure_reason: str | None = None


@dataclass(frozen=True)
class PatchCheck:
    allowed: bool
    violations: tuple[str, ...]
    changed_files: tuple[str, ...]
    added_lines: int
    deleted_lines: int


@dataclass(frozen=True)
class ReviewResult:
    approved: bool
    risk: Literal["low", "medium", "high"]
    findings: tuple[str, ...]
    reason: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class VerificationResult:
    target_passed: bool
    full_suite_passed: bool
    regression_failures: tuple[str, ...]
    patch_check: PatchCheck
    target_run: TestRun | None = None
    full_run: TestRun | None = None

    @property
    def passed(self) -> bool:
        return (
            self.target_passed
            and self.full_suite_passed
            and not self.regression_failures
            and self.patch_check.allowed
        )


@dataclass(frozen=True)
class RunResult:
    status: Literal["success", "failed", "dry_run"]
    attempts: int
    artifact_dir: Path
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
