import json

import pytest

from pyrepair.testing import TestRunner as PytestRunner
from pyrepair.tools import ToolErrorInfo, ToolRegistry, ToolResult
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


def test_tool_error_serializes_with_stable_shape():
    result = ToolResult(
        False,
        {},
        ToolErrorInfo("file_not_found", "File does not exist.", False),
    )

    assert json.loads(result.to_json()) == {
        "ok": False,
        "data": {},
        "error": {
            "code": "file_not_found",
            "message": "File does not exist.",
            "retryable": False,
        },
        "metadata": {},
    }


def test_read_file_rejects_parent_escape(tool_registry):
    result = tool_registry.execute("read_file", {"path": "../secret.txt"})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "path_outside_workspace"


def test_read_file_returns_lines_and_next_cursor(tool_registry):
    result = tool_registry.execute(
        "read_file",
        {"path": "app.py", "start_line": 1, "end_line": 1},
    )

    assert result.data == {
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "total_lines": 2,
        "content": "1: def add(a, b):",
        "truncated": True,
        "next_start_line": 2,
    }


def test_read_file_limits_large_content(tool_registry):
    (tool_registry.workspace / "large.py").write_text("x" * 20_100, encoding="utf-8")

    result = tool_registry.execute("read_file", {"path": "large.py"})

    assert result.ok is True
    assert len(result.data["content"]) <= 20_000
    assert result.data["truncated"] is True


def test_read_file_returns_structured_missing_file_error(tool_registry):
    result = tool_registry.execute("read_file", {"path": "missing.py"})

    assert result.error == ToolErrorInfo("file_not_found", "File does not exist.")


def test_read_file_rejects_non_utf8_content(tool_registry):
    (tool_registry.workspace / "binary.txt").write_bytes(b"\xff\xfe")

    result = tool_registry.execute("read_file", {"path": "binary.txt"})

    assert result.error is not None
    assert result.error.code == "unsupported_text_file"


def test_replace_text_requires_exactly_one_match(tool_registry):
    path = tool_registry.workspace / "app.py"
    path.write_text("x = 1\nx = 1\n", encoding="utf-8")

    result = tool_registry.execute(
        "replace_text",
        {"path": "app.py", "old_text": "x = 1", "new_text": "x = 2"},
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "expected_one_match"
    assert result.metadata["matches"] == 2
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

    assert result.error is not None
    assert result.error.code == "protected_test_path"


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

    assert replacement.data == {"path": "app.py", "replacements": 1}
    assert diff.ok is True
    assert diff.data["changed_files"] == ["app.py"]
    assert diff.data["added_lines"] == 1
    assert diff.data["deleted_lines"] == 1
    assert "-    return a - b" in diff.data["diff"]
    assert "+    return a + b" in diff.data["diff"]


def test_search_code_paginates_without_losing_total(tool_registry):
    for index in range(55):
        (tool_registry.workspace / f"module_{index:02}.py").write_text(
            f"needle = {index}\n",
            encoding="utf-8",
        )
    (tool_registry.workspace / "notes.md").write_text("needle\n", encoding="utf-8")

    result = tool_registry.execute(
        "search_code",
        {"query": "needle", "offset": 10, "limit": 5},
    )

    assert len(result.data["matches"]) == 5
    assert result.data["total_matches"] == 55
    assert result.data["next_offset"] == 15
    assert all(item["path"].endswith(".py") for item in result.data["matches"])


def test_run_target_test_uses_fixed_parser_node_id(tool_registry):
    first = tool_registry.execute("run_target_test", {})
    extra = tool_registry.execute("run_target_test", {"command": "whoami"})

    assert first.ok is True
    assert first.data["passed"] is False
    assert first.data["exit_code"] == 1
    assert first.data["target"] == "tests/test_app.py::test_add"
    assert extra.error is not None
    assert extra.error.code == "invalid_arguments"


def test_run_target_test_rejects_missing_parser_node_id(tool_registry):
    registry = ToolRegistry(
        session=tool_registry.session,
        runner=PytestRunner(timeout_seconds=5),
        target_node_id=None,
    )

    result = registry.execute("run_target_test", {})

    assert result.error is not None
    assert result.error.code == "target_test_unavailable"


def test_registry_exports_eight_openai_function_schemas(tool_registry):
    names = {item["function"]["name"] for item in tool_registry.schemas()}

    assert names == {
        "read_file",
        "search_code",
        "find_symbol",
        "find_references",
        "inspect_module",
        "replace_text",
        "show_diff",
        "run_target_test",
    }


def test_symbol_and_module_tools_return_locations(tool_registry):
    symbol = tool_registry.execute("find_symbol", {"name": "add"})
    module = tool_registry.execute("inspect_module", {"path": "app.py"})

    assert symbol.data["definitions"][0]["path"] == "app.py"
    assert module.data["symbols"][0]["name"] == "add"
    assert module.data["parse_error"] is None


def test_find_references_returns_possible_ast_locations(tool_registry):
    result = tool_registry.execute("find_references", {"name": "add"})

    assert result.ok is True
    assert result.data["name"] == "add"
    assert result.data["total_matches"] >= 2
    assert any(
        item["path"] == "tests/test_app.py"
        for item in result.data["references"]
    )


def test_registry_returns_structured_unknown_tool_error(tool_registry):
    result = tool_registry.execute("delete_repository", {})

    assert result.error is not None
    assert result.error.code == "unknown_tool"
    assert json.loads(result.to_json())["error"]["code"] == "unknown_tool"
