import json

import pytest

from pyrepair.testing import TestRunner as PytestRunner
from pyrepair.tools import ToolRegistry, ToolResult
from pyrepair.workspace import WorkspaceManager


@pytest.fixture
def tool_registry(tmp_path):
    repo = tmp_path / "repo"
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "notes.md").write_text("repair notes\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text(
        "from app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    session = WorkspaceManager().create(repo)
    registry = ToolRegistry(
        session=session,
        runner=PytestRunner(timeout_seconds=5),
        target_node_id="tests/test_app.py::test_add",
    )
    yield registry
    session.cleanup()


def test_read_file_rejects_parent_escape(tool_registry):
    result = tool_registry.execute("read_file", {"path": "../secret.txt"})

    assert result.ok is False
    assert result.error == "path_outside_workspace"


def test_read_file_returns_text_and_limits_size(tool_registry):
    (tool_registry.workspace / "large.py").write_text("x" * 20_100, encoding="utf-8")

    result = tool_registry.execute("read_file", {"path": "large.py"})

    assert result.ok is True
    assert len(result.content) <= 20_100
    assert result.content.endswith("[TRUNCATED]")


def test_read_file_returns_structured_missing_file_error(tool_registry):
    result = tool_registry.execute("read_file", {"path": "missing.py"})

    assert result == ToolResult(ok=False, error="file_not_found")


def test_read_file_rejects_non_utf8_content(tool_registry):
    (tool_registry.workspace / "binary.txt").write_bytes(b"\xff\xfe")

    result = tool_registry.execute("read_file", {"path": "binary.txt"})

    assert result == ToolResult(ok=False, error="unsupported_text_file")


def test_replace_text_requires_exactly_one_match(tool_registry):
    path = tool_registry.workspace / "app.py"
    path.write_text("x = 1\nx = 1\n", encoding="utf-8")

    result = tool_registry.execute(
        "replace_text",
        {"path": "app.py", "old_text": "x = 1", "new_text": "x = 2"},
    )

    assert result.ok is False
    assert result.error == "expected_one_match_found_2"
    assert path.read_text(encoding="utf-8") == "x = 1\nx = 1\n"


def test_replace_text_rejects_test_files(tool_registry):
    result = tool_registry.execute(
        "replace_text",
        {
            "path": "tests/test_app.py",
            "old_text": "assert add(2, 3) == 5",
            "new_text": "assert True",
        },
    )

    assert result.ok is False
    assert result.error == "protected_test_path"


def test_replace_text_changes_source_and_show_diff_reports_it(tool_registry):
    replacement = tool_registry.execute(
        "replace_text",
        {
            "path": "app.py",
            "old_text": "return a - b",
            "new_text": "return a + b",
        },
    )
    diff = tool_registry.execute("show_diff", {})

    assert replacement.ok is True
    assert diff.ok is True
    assert "-    return a - b" in diff.content
    assert "+    return a + b" in diff.content


def test_search_code_only_searches_python_and_limits_results(tool_registry):
    for index in range(55):
        (tool_registry.workspace / f"module_{index:02}.py").write_text(
            f"needle = {index}\n", encoding="utf-8"
        )
    (tool_registry.workspace / "notes.md").write_text("needle\n", encoding="utf-8")

    result = tool_registry.execute("search_code", {"query": "needle"})

    assert result.ok is True
    lines = result.content.splitlines()
    assert len(lines) == 50
    assert all(line.split(":", 1)[0].endswith(".py") for line in lines)


def test_run_target_test_uses_fixed_parser_node_id(tool_registry):
    first = tool_registry.execute("run_target_test", {})
    extra = tool_registry.execute("run_target_test", {"command": "whoami"})

    assert first.ok is True
    payload = json.loads(first.content)
    assert payload["exit_code"] == 1
    assert payload["target"] == "tests/test_app.py::test_add"
    assert extra.ok is False
    assert extra.error == "invalid_arguments"


def test_run_target_test_rejects_missing_parser_node_id(tool_registry):
    registry = ToolRegistry(
        session=tool_registry.session,
        runner=PytestRunner(timeout_seconds=5),
        target_node_id=None,
    )

    result = registry.execute("run_target_test", {})

    assert result == ToolResult(ok=False, error="target_test_unavailable")


def test_registry_exports_five_openai_function_schemas(tool_registry):
    schemas = tool_registry.schemas()

    assert {item["function"]["name"] for item in schemas} == {
        "read_file",
        "search_code",
        "replace_text",
        "show_diff",
        "run_target_test",
    }
    assert all(item["type"] == "function" for item in schemas)


def test_registry_returns_structured_unknown_tool_error(tool_registry):
    result = tool_registry.execute("delete_repository", {})

    assert result == ToolResult(ok=False, error="unknown_tool")
    assert json.loads(result.to_json()) == {
        "ok": False,
        "content": "",
        "error": "unknown_tool",
    }
