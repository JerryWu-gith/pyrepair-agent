import json

import pytest

from pyrepair.context_builder import ContextBundle, ContextSnippet
from pyrepair.feedback import AttemptFeedback
from pyrepair.models import FailureReport, ModelTurn, ToolCallRequest
from pyrepair.repair_agent import RepairAgent
from pyrepair.testing import TestRunner as PytestRunner
from pyrepair.tools import ToolRegistry
from pyrepair.workspace import WorkspaceManager
from tests.fakes import FakeLLM, model_text_turn, model_tool_turn


@pytest.fixture
def registry(tmp_path):
    repo = tmp_path / "repo"
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text(
        "from app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    session = WorkspaceManager().create(repo)
    tool_registry = ToolRegistry(
        session,
        PytestRunner(timeout_seconds=5),
        "tests/test_app.py::test_add",
    )
    yield tool_registry
    session.cleanup()


def failure_report() -> FailureReport:
    return FailureReport(
        node_id="tests/test_app.py::test_add",
        exception_type="AssertionError",
        traceback="E assert -1 == 5",
        summary="assert -1 == 5",
        related_files=("app.py", "tests/test_app.py"),
    )


def context_bundle(path: str) -> ContextBundle:
    snippet = ContextSnippet(
        path,
        1,
        2,
        "add",
        "traceback_file",
        100,
        "def add(a, b):\n    return a - b",
    )
    return ContextBundle("files: app.py", (snippet,), (path,), 60, False)


def extract_status(messages: list[dict]) -> dict:
    content = messages[-1]["content"]
    assert content.startswith("<agent_status>")
    return json.loads(
        content.removeprefix("<agent_status>").removesuffix("</agent_status>")
    )


def edit_turn():
    return model_tool_turn(
        "edit",
        "replace_text",
        {
            "path": "app.py",
            "old_text": "return a - b",
            "new_text": "return a + b",
        },
    )


def test_agent_executes_tools_and_returns_results_to_model(registry):
    llm = FakeLLM(
        [
            model_tool_turn("call-1", "read_file", {"path": "app.py"}, reasoning="inspect"),
            model_tool_turn(
                "call-2",
                "replace_text",
                {
                    "path": "app.py",
                    "old_text": "return a - b",
                    "new_text": "return a + b",
                },
                reasoning="repair",
            ),
            model_tool_turn("diff", "show_diff", {}, reasoning="inspect patch"),
            model_tool_turn("test", "run_target_test", {}, reasoning="verify"),
            model_text_turn("repair complete", reasoning="done"),
        ]
    )

    result = RepairAgent(llm, registry, max_tool_calls=8).run(failure_report())

    assert result.completed is True
    assert len(result.turns) == 5
    assert "return a + b" in (registry.workspace / "app.py").read_text(encoding="utf-8")
    second_request_messages = llm.requests[1][0]
    tool_message = next(
        item for item in second_request_messages if item.get("tool_call_id") == "call-1"
    )
    assert tool_message["role"] == "tool"
    tool_payload = json.loads(tool_message["content"])
    assert tool_payload["ok"] is True
    assert tool_payload["metadata"]["trusted"] is False


def test_agent_stops_at_tool_call_limit(registry):
    llm = FakeLLM(
        [
            model_tool_turn("call-1", "read_file", {"path": "app.py"}),
            model_tool_turn("call-2", "search_code", {"query": "add"}),
            model_tool_turn("call-3", "find_symbol", {"name": "add"}),
            model_tool_turn("call-4", "inspect_module", {"path": "app.py"}),
        ]
    )

    result = RepairAgent(llm, registry, max_tool_calls=3).run(failure_report())

    assert result.completed is False
    assert result.failure_reason == "max_tool_calls_exceeded"
    assert len(result.turns) == 4
    assert len(llm.requests) == 4


def test_agent_returns_unknown_tool_error_to_model(registry):
    llm = FakeLLM(
        [
            model_tool_turn("call-1", "delete_repository", {}),
            model_text_turn("cannot use that tool"),
        ]
    )

    result = RepairAgent(llm, registry, max_tool_calls=3).run(failure_report())

    assert result.completed is True
    assert "unknown_tool" in llm.requests[1][0][-1]["content"]


def test_agent_can_end_without_tool_call(registry):
    result = RepairAgent(
        FakeLLM([model_text_turn("not enough evidence")]),
        registry,
        max_tool_calls=3,
    ).run(failure_report())

    assert result.completed is True
    assert result.failure_reason is None


def test_agent_includes_structured_previous_attempts_in_initial_request(registry):
    llm = FakeLLM([model_text_turn("stop")])
    feedback = AttemptFeedback(
        1,
        "policy_rejected",
        ("app.py",),
        "diff --git a/app.py b/app.py",
        ("protected_path",),
        (),
        None,
        (),
        "Avoid the policy violation.",
    )

    RepairAgent(llm, registry, max_tool_calls=3).run(
        failure_report(),
        previous_feedback=(feedback,),
    )

    initial_messages = llm.requests[0][0]
    assert initial_messages[0]["role"] == "system"
    assert "禁止修改测试" in initial_messages[0]["content"]
    user_payload = json.loads(initial_messages[1]["content"])
    assert user_payload["previous_attempts"][0]["outcome"] == "policy_rejected"
    assert user_payload["previous_attempts"][0]["policy_violations"] == [
        "protected_path"
    ]
    assert user_payload["previous_attempts"][0]["trusted"] is False


def test_agent_initial_payload_contains_untrusted_context(registry):
    llm = FakeLLM([model_text_turn("stop")])

    RepairAgent(llm, registry).run(
        failure_report(),
        context=context_bundle("src/app.py"),
    )

    payload = json.loads(llm.requests[0][0][1]["content"])
    assert payload["failure"]["trusted"] is False
    assert payload["context"]["trusted"] is False
    assert payload["context"]["snippets"][0]["path"] == "src/app.py"
    assert payload["context"]["snippets"][0]["trusted"] is False
    assert "不可信数据" in llm.requests[0][0][0]["content"]


def test_agent_does_not_execute_tool_call_beyond_limit(registry):
    turn = ModelTurn(
        content="",
        reasoning_content="batch",
        tool_calls=(
            ToolCallRequest("call-1", "read_file", {"path": "app.py"}),
            ToolCallRequest("call-2", "replace_text", {
                "path": "app.py",
                "old_text": "return a - b",
                "new_text": "return a + b",
            }),
        ),
    )
    llm = FakeLLM([turn])

    result = RepairAgent(llm, registry, max_tool_calls=1).run(failure_report())

    assert result.completed is False
    assert result.failure_reason == "max_tool_calls_exceeded"
    assert "return a - b" in (registry.workspace / "app.py").read_text(encoding="utf-8")


def test_agent_injects_fresh_status_before_every_model_call(registry):
    llm = FakeLLM(
        [
            model_tool_turn("read", "read_file", {"path": "app.py"}),
            model_text_turn("stop"),
        ]
    )

    result = RepairAgent(llm, registry, max_tool_calls=3).run(
        failure_report(),
        attempt=2,
        max_attempts=3,
    )

    first = extract_status(llm.requests[0][0])
    second = extract_status(llm.requests[1][0])
    assert first["attempt"] == 2
    assert first["tool_calls_used"] == 0
    assert second["tool_calls_used"] == 1
    assert second["files_read"] == ["app.py"]
    assert result.final_status is not None
    assert result.final_status.tool_calls_used == 1


def test_agent_cannot_finish_after_edit_without_diff_and_test(registry):
    llm = FakeLLM([edit_turn(), model_text_turn("done")])

    result = RepairAgent(llm, registry, max_tool_calls=1).run(failure_report())

    assert result.completed is False
    assert result.failure_reason == "required_verification_missing"


def test_agent_finishes_after_edit_diff_and_target_test(registry):
    llm = FakeLLM(
        [
            edit_turn(),
            model_tool_turn("diff", "show_diff", {}),
            model_tool_turn("test", "run_target_test", {}),
            model_text_turn("done"),
        ]
    )

    result = RepairAgent(llm, registry, max_tool_calls=3).run(failure_report())

    assert result.completed is True
    assert result.final_status is not None
    assert result.final_status.diff_inspected is True
    assert result.final_status.target_test_run is True


def test_agent_records_loop_guard_reason(registry):
    repeated = model_tool_turn("read", "read_file", {"path": "app.py"})
    llm = FakeLLM([repeated, repeated, repeated])

    result = RepairAgent(llm, registry, max_tool_calls=5).run(failure_report())

    assert result.completed is False
    assert result.failure_reason == "repeated_tool_call"
    assert "repeated_tool_call" in result.guard_events
