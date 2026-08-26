from dataclasses import replace

from pyrepair.agent_state import AgentRuntimeState
from pyrepair.loop_guard import CompletionPolicy, GuardDecision, LoopGuard
from pyrepair.models import AgentStatus
from pyrepair.tools import ToolErrorInfo, ToolResult


def ok_result(data: dict) -> ToolResult:
    return ToolResult(True, data)


def test_third_consecutive_identical_call_is_blocked():
    state = AgentRuntimeState(1, 3, 8)
    guard = LoopGuard()
    call = {"path": "app.py"}
    for _ in range(2):
        assert guard.before_tool("read_file", call, state).blocked is False
        progress = state.record_tool("read_file", call, ok_result({"content": "x"}))
        guard.after_tool(progress, state)

    assert guard.before_tool("read_file", call, state) == GuardDecision(
        True,
        "repeated_tool_call",
        None,
    )


def test_second_identical_call_is_allowed_with_guidance():
    state = AgentRuntimeState(1, 3, 8)
    guard = LoopGuard()
    call = {"path": "app.py"}
    state.record_tool("read_file", call, ok_result({"content": "x"}))

    decision = guard.before_tool("read_file", call, state)

    assert decision.blocked is False
    assert decision.guidance is not None


def test_same_error_twice_blocks_a_later_identical_call():
    state = AgentRuntimeState(1, 3, 8)
    guard = LoopGuard()
    call = {"path": "missing.py"}
    error = ToolResult(False, {}, ToolErrorInfo("file_not_found", "missing"))
    state.record_tool("read_file", call, error)
    state.record_tool("search_code", {"query": "x"}, ok_result({"matches": []}))
    state.record_tool("read_file", call, error)

    assert guard.before_tool("read_file", call, state).reason == "repeated_tool_error"


def test_third_no_progress_step_warns_and_fourth_blocks():
    state = AgentRuntimeState(1, 3, 10)
    guard = LoopGuard()
    for _ in range(4):
        progress = state.record_tool("read_file", {"path": "app.py"}, ok_result({"x": 1}))
    third = guard.after_tool(progress, state)
    assert third.blocked is False
    assert third.guidance is not None

    progress = state.record_tool("read_file", {"path": "app.py"}, ok_result({"x": 1}))
    fourth = guard.after_tool(progress, state)
    assert fourth == GuardDecision(True, "no_progress", None)


def test_new_evidence_resets_no_progress_counter():
    state = AgentRuntimeState(1, 3, 10)
    state.record_tool("read_file", {"path": "app.py"}, ok_result({"content": "old"}))
    state.record_tool("read_file", {"path": "app.py"}, ok_result({"content": "old"}))
    state.record_tool("read_file", {"path": "app.py"}, ok_result({"content": "new"}))

    assert state.snapshot().no_progress_steps == 0


def status_with_change() -> AgentStatus:
    return AgentStatus(
        1,
        3,
        1,
        8,
        (),
        ("app.py",),
        "replace_text",
        None,
        1,
        0,
        False,
        False,
    )


def test_completion_requires_diff_and_target_test_after_change():
    status = replace(status_with_change(), diff_inspected=True, target_test_run=False)

    decision = CompletionPolicy().evaluate(status, True, 2)

    assert decision.continue_loop is True
    assert decision.guidance is not None
    assert "run_target_test" in decision.guidance


def test_completion_allows_no_change_or_fully_verified_change():
    no_change = CompletionPolicy().evaluate(status_with_change(), False, 2)
    verified = CompletionPolicy().evaluate(
        replace(status_with_change(), diff_inspected=True, target_test_run=True),
        True,
        0,
    )

    assert no_change.complete is True
    assert verified.complete is True


def test_completion_fails_when_verification_is_missing_and_budget_exhausted():
    decision = CompletionPolicy().evaluate(status_with_change(), True, 0)

    assert decision.complete is False
    assert decision.continue_loop is False
    assert decision.reason == "required_verification_missing"

