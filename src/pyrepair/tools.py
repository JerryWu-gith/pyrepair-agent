from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypeAlias

from .testing import TestRunner
from .workspace import EXCLUDED_NAMES, WorkspaceError, WorkspaceSession

MAX_READ_CHARS = 20_000
MAX_READ_LINES = 200
MAX_SEARCH_RESULTS = 50
MAX_DIFF_CHARS = 20_000
MAX_TEST_OUTPUT_CHARS = 4_000
READABLE_SUFFIXES = {
    ".py",
    ".pyi",
    ".toml",
    ".ini",
    ".cfg",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
}

JSONScalar = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class ToolErrorInfo:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, JSONValue]
    error: ToolErrorInfo | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def tool_error(code: str, message: str, *, retryable: bool = False) -> ToolResult:
    return ToolResult(False, {}, ToolErrorInfo(code, message, retryable))


class ToolError(RuntimeError):
    """Raised for a safe, user-correctable tool error."""


class BaseTool:
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read numbered lines from a UTF-8 text file in the repair workspace."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not _valid_keys(arguments, {"path"}, {"start_line", "end_line"}):
            return _invalid_arguments()
        path_value = arguments.get("path")
        start = arguments.get("start_line", 1)
        end_value = arguments.get("end_line")
        if (
            not isinstance(path_value, str)
            or not isinstance(start, int)
            or isinstance(start, bool)
            or start < 1
            or (end_value is not None and (
                not isinstance(end_value, int)
                or isinstance(end_value, bool)
                or end_value < start
            ))
        ):
            return _invalid_arguments()
        try:
            path = resolve_inside(self.root, path_value)
        except ToolError:
            return tool_error("path_outside_workspace", "Path must stay inside the workspace.")
        if not path.is_file():
            return tool_error("file_not_found", "File does not exist.")
        if path.suffix.lower() not in READABLE_SUFFIXES:
            return tool_error("unsupported_text_file", "File type is not readable as text.")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return tool_error("unsupported_text_file", "File is not valid UTF-8 text.")

        total = len(lines)
        requested_end = end_value if end_value is not None else start + MAX_READ_LINES - 1
        actual_end = min(requested_end, total)
        selected = lines[start - 1 : actual_end] if start <= total else []
        numbered = "\n".join(
            f"{line_number}: {line}"
            for line_number, line in enumerate(selected, start=start)
        )
        char_truncated = len(numbered) > MAX_READ_CHARS
        if char_truncated:
            marker = "\n[TRUNCATED]"
            numbered = numbered[: MAX_READ_CHARS - len(marker)] + marker
        more_lines = actual_end < total
        return ToolResult(
            True,
            {
                "path": path.relative_to(self.root).as_posix(),
                "start_line": start,
                "end_line": actual_end,
                "total_lines": total,
                "content": numbered,
                "truncated": more_lines or char_truncated,
                "next_start_line": actual_end + 1 if more_lines else None,
            },
        )


class SearchCodeTool(BaseTool):
    name = "search_code"
    description = "Search literal text in Python files with stable pagination."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Literal text to find"},
            "path": {"type": "string", "description": "Optional file or directory scope"},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_RESULTS},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not _valid_keys(arguments, {"query"}, {"path", "offset", "limit"}):
            return _invalid_arguments()
        query = arguments.get("query")
        scope_value = arguments.get("path", ".")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", MAX_SEARCH_RESULTS)
        if (
            not isinstance(query, str)
            or not query
            or not isinstance(scope_value, str)
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_SEARCH_RESULTS
        ):
            return _invalid_arguments()
        try:
            scope = resolve_inside(self.root, scope_value)
        except ToolError:
            return tool_error("path_outside_workspace", "Path must stay inside the workspace.")
        paths = [scope] if scope.is_file() else sorted(scope.rglob("*.py")) if scope.is_dir() else []
        all_matches: list[JSONValue] = []
        for path in paths:
            if path.suffix.lower() != ".py":
                continue
            relative_path = path.relative_to(self.root)
            if any(part in EXCLUDED_NAMES for part in relative_path.parts):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if query in line:
                    all_matches.append(
                        {
                            "path": relative_path.as_posix(),
                            "line": line_number,
                            "content": line[:500],
                        }
                    )
        page = all_matches[offset : offset + limit]
        next_offset = offset + len(page)
        return ToolResult(
            True,
            {
                "query": query,
                "path": scope_value,
                "matches": page,
                "total_matches": len(all_matches),
                "offset": offset,
                "limit": limit,
                "next_offset": next_offset if next_offset < len(all_matches) else None,
            },
        )


class ReplaceTextTool(BaseTool):
    name = "replace_text"
    description = "Replace text that appears exactly once in a non-test Python source file."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative Python path"},
            "old_text": {"type": "string", "description": "Exact existing text"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        expected = {"path", "old_text", "new_text"}
        if set(arguments) != expected or not all(
            isinstance(arguments.get(key), str) for key in expected
        ):
            return _invalid_arguments()
        old_text = arguments["old_text"]
        if not old_text:
            return _invalid_arguments()
        try:
            path = resolve_inside(self.root, arguments["path"])
        except ToolError:
            return tool_error("path_outside_workspace", "Path must stay inside the workspace.")
        relative = path.relative_to(self.root)
        if any(part.lower() == "tests" for part in relative.parts):
            return tool_error("protected_test_path", "Test files cannot be modified.")
        if path.suffix.lower() not in {".py", ".pyi"}:
            return tool_error("source_files_only", "Only Python source files can be modified.")
        if not path.is_file():
            return tool_error("file_not_found", "File does not exist.")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return tool_error("unsupported_text_file", "File is not valid UTF-8 text.")
        count = content.count(old_text)
        if count != 1:
            result = tool_error("expected_one_match", "Replacement text must match exactly once.")
            return ToolResult(result.ok, result.data, result.error, {"matches": count})
        path.write_text(content.replace(old_text, arguments["new_text"], 1), encoding="utf-8")
        return ToolResult(True, {"path": relative.as_posix(), "replacements": 1})


class ShowDiffTool(BaseTool):
    name = "show_diff"
    description = "Show the current candidate unified diff and change statistics."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, session: WorkspaceSession) -> None:
        self.session = session

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if arguments:
            return _invalid_arguments()
        try:
            snapshot = self.session.snapshot()
        except WorkspaceError:
            return tool_error("diff_unavailable", "Candidate diff could not be generated.")
        raw_diff = snapshot.text
        truncated = len(raw_diff) > MAX_DIFF_CHARS
        limited_diff = raw_diff[:MAX_DIFF_CHARS]
        return ToolResult(
            True,
            {
                "diff": limited_diff,
                "changed_files": [item.path for item in snapshot.changes],
                "added_lines": sum(item.added_lines for item in snapshot.changes),
                "deleted_lines": sum(item.deleted_lines for item in snapshot.changes),
                "truncated": truncated,
            },
        )


class RunTargetTestTool(BaseTool):
    name = "run_target_test"
    description = "Run only the fixed pytest node id identified from the original failure."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, root: Path, runner: TestRunner, target_node_id: str | None) -> None:
        self.root = root
        self.runner = runner
        self.target_node_id = target_node_id

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if arguments:
            return _invalid_arguments()
        if not self.target_node_id:
            return tool_error("target_test_unavailable", "No target pytest node id is available.")
        run = self.runner.run(self.root, self.target_node_id)
        if run.timed_out:
            return tool_error("target_test_timeout", "Target test timed out.", retryable=True)
        if run.launch_error:
            return tool_error(
                "target_test_launch_error",
                "Target test process could not be launched.",
                retryable=True,
            )
        return ToolResult(
            True,
            {
                "target": self.target_node_id,
                "passed": run.exit_code == 0,
                "exit_code": run.exit_code,
                "stdout_tail": run.stdout[-MAX_TEST_OUTPUT_CHARS:],
                "stderr_tail": run.stderr[-MAX_TEST_OUTPUT_CHARS:],
                "duration_ms": run.duration_ms,
                "timed_out": False,
            },
        )


class ToolRegistry:
    def __init__(
        self,
        session: WorkspaceSession,
        runner: TestRunner,
        target_node_id: str | None,
    ) -> None:
        self.session = session
        self.workspace = session.working
        tools: tuple[BaseTool, ...] = (
            ReadFileTool(self.workspace),
            SearchCodeTool(self.workspace),
            ReplaceTextTool(self.workspace),
            ShowDiffTool(session),
            RunTargetTestTool(self.workspace, runner, target_node_id),
        )
        self._tools = {tool.name: tool for tool in tools}

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return tool_error("unknown_tool", "Requested tool is not available.")
        if not isinstance(arguments, dict):
            return _invalid_arguments()
        return tool.execute(arguments)


def resolve_inside(root: Path, user_path: str) -> Path:
    candidate = (root / user_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ToolError("path_outside_workspace") from exc
    return candidate


def _valid_keys(arguments: dict[str, Any], required: set[str], optional: set[str]) -> bool:
    keys = set(arguments)
    return required <= keys <= required | optional


def _invalid_arguments() -> ToolResult:
    return tool_error("invalid_arguments", "Tool arguments do not match the schema.")
