from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_state import AgentRuntimeState, ToolProgress, call_fingerprint
from .models import AgentStatus


@dataclass(frozen=True)
class GuardDecision:
    blocked: bool
    reason: str | None = None
    guidance: str | None = None


@dataclass(frozen=True)
class CompletionDecision:
    complete: bool
    continue_loop: bool
    reason: str | None = None
    guidance: str | None = None


class LoopGuard:
    def before_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        state: AgentRuntimeState,
    ) -> GuardDecision:
        fingerprint = call_fingerprint(name, arguments)
        if fingerprint == state.last_call_fingerprint and state.repeated_call_count >= 2:
            return GuardDecision(True, "repeated_tool_call")
        if state.identical_error_count(fingerprint) >= 2:
            return GuardDecision(True, "repeated_tool_error")
        if fingerprint == state.last_call_fingerprint and state.repeated_call_count == 1:
            return GuardDecision(
                False,
                guidance="This call repeats the previous request; change strategy if unchanged.",
            )
        return GuardDecision(False)

    def after_tool(
        self,
        progress: ToolProgress,
        state: AgentRuntimeState,
    ) -> GuardDecision:
        del progress
        if state.no_progress_steps >= 4:
            return GuardDecision(True, "no_progress")
        if state.no_progress_steps == 3:
            return GuardDecision(
                False,
                guidance="Change strategy and gather new evidence before continuing.",
            )
        if state.max_tool_calls - state.tool_calls_used <= 2:
            return GuardDecision(
                False,
                guidance="Tool budget is low; inspect the diff and run the target test.",
            )
        return GuardDecision(False)


class CompletionPolicy:
    def evaluate(
        self,
        status: AgentStatus,
        has_changes: bool,
        budget_remaining: int,
    ) -> CompletionDecision:
        if not has_changes:
            return CompletionDecision(True, False)
        missing: list[str] = []
        if not status.diff_inspected:
            missing.append("show_diff")
        if not status.target_test_run:
            missing.append("run_target_test")
        if not missing:
            return CompletionDecision(True, False)
        if budget_remaining > 0:
            return CompletionDecision(
                False,
                True,
                guidance="Required before finishing: " + ", ".join(missing),
            )
        return CompletionDecision(False, False, "required_verification_missing")
