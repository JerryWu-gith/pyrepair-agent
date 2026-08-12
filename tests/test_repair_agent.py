import json

import pytest

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
            model_text_turn("repair complete", reasoning="done"),
        ]
    )

    result = RepairAgent(llm, registry, max_tool_calls=8).run(failure_report())

    assert result.completed is True
    assert len(result.turns) == 3
    assert "return a + b" in (registry.workspace / "app.py").read_text(encoding="utf-8")
    second_request_messages = llm.requests[1][0]
    assert second_request_messages[-2]["role"] == "assistant"
    assert second_request_messages[-2]["reasoning_content"] == "inspect"
    assert second_request_messages[-1]["role"] == "tool"
    assert second_request_messages[-1]["tool_call_id"] == "call-1"
    assert json.loads(second_request_messages[-1]["content"])["ok"] is True


def test_agent_stops_at_tool_call_limit(registry):
    llm = FakeLLM(
        [model_tool_turn(f"call-{index}", "show_diff", {}) for index in range(4)]
    )

    result = RepairAgent(llm, registry, max_tool_calls=3).run(failure_report())

    assert result.completed is False
    assert result.failure_reason == "max_tool_calls_exceeded"
    assert len(result.turns) == 3
    assert len(llm.requests) == 3


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


def test_agent_includes_previous_attempt_evidence_in_initial_request(registry):
    llm = FakeLLM([model_text_turn("stop")])

    RepairAgent(llm, registry, max_tool_calls=3).run(
        failure_report(),
        previous_evidence=("protected_path:tests/test_app.py", "target test still fails"),
    )

    initial_messages = llm.requests[0][0]
    assert initial_messages[0]["role"] == "system"
    assert "禁止修改测试" in initial_messages[0]["content"]
    user_payload = json.loads(initial_messages[1]["content"])
    assert user_payload["previous_evidence"] == [
        "protected_path:tests/test_app.py",
        "target test still fails",
    ]


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
