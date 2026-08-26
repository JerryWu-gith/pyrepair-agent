from pyrepair.agent_state import AgentRuntimeState, call_fingerprint
from pyrepair.tools import ToolErrorInfo, ToolResult


def ok_result(data: dict) -> ToolResult:
    return ToolResult(True, data)


def test_successful_edit_resets_post_edit_verification():
    state = AgentRuntimeState(1, 3, 8)
    state.record_tool("show_diff", {}, ok_result({"diff": ""}))
    state.record_tool("run_target_test", {}, ok_result({"passed": False}))
    state.record_tool(
        "replace_text",
        {"path": "app.py"},
        ok_result({"path": "app.py", "replacements": 1}),
    )

    status = state.snapshot()

    assert status.changed_files == ("app.py",)
    assert status.diff_inspected is False
    assert status.target_test_run is False


def test_new_read_is_progress_but_identical_result_is_not():
    state = AgentRuntimeState(1, 3, 8)
    first = state.record_tool(
        "read_file",
        {"path": "app.py", "start_line": 1, "end_line": 10},
        ok_result({"path": "app.py", "content": "x"}),
    )
    second = state.record_tool(
        "read_file",
        {"end_line": 10, "path": "app.py", "start_line": 1},
        ok_result({"path": "app.py", "content": "x"}),
    )

    assert first.progressed is True
    assert second.progressed is False
    assert state.snapshot().no_progress_steps == 1


def test_status_snapshot_sorts_file_sets():
    state = AgentRuntimeState(2, 3, 8)
    state.record_tool("read_file", {"path": "z.py"}, ok_result({"path": "z.py"}))
    state.record_tool("read_file", {"path": "a.py"}, ok_result({"path": "a.py"}))

    assert state.snapshot().files_read == ("a.py", "z.py")


def test_call_fingerprint_is_independent_of_argument_order():
    first = call_fingerprint("read_file", {"path": "app.py", "start_line": 1})
    second = call_fingerprint("read_file", {"start_line": 1, "path": "app.py"})

    assert first == second


def test_identical_error_count_is_tracked_per_call():
    state = AgentRuntimeState(1, 3, 8)
    arguments = {"path": "missing.py"}
    error = ToolResult(
        False,
        {},
        ToolErrorInfo("file_not_found", "File does not exist."),
    )

    state.record_tool("read_file", arguments, error)
    state.record_tool("read_file", arguments, error)

    assert state.identical_error_count(call_fingerprint("read_file", arguments)) == 2
    assert state.snapshot().last_error == "file_not_found"


def test_test_duration_and_pytest_timing_do_not_count_as_progress():
    state = AgentRuntimeState(1, 3, 8)
    arguments: dict = {}
    first = ok_result(
        {
            "target": "tests/test_app.py::test_add",
            "passed": False,
            "exit_code": 1,
            "stdout_tail": "1 failed in 0.11s",
            "stderr_tail": "",
            "duration_ms": 110,
            "timed_out": False,
        }
    )
    second = ok_result(
        {
            **first.data,
            "stdout_tail": "1 failed in 0.99s",
            "duration_ms": 990,
        }
    )

    initial = state.record_tool("run_target_test", arguments, first)
    repeated = state.record_tool("run_target_test", arguments, second)

    assert initial.progressed is True
    assert repeated.progressed is False
    assert state.snapshot().no_progress_steps == 1
