from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypeAlias

from .repository_index import RepositoryIndex, build_repository_index
from .testing import TestExecutor
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
            "start_column": {"type": "integer", "minimum": 0},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not _valid_keys(
            arguments,
            {"path"},
            {"start_line", "start_column", "end_line"},
        ):
            return _invalid_arguments()
        path_value = arguments.get("path")
        start = arguments.get("start_line", 1)
        start_column = arguments.get("start_column", 0)
        end_value = arguments.get("end_line")
        if (
            not isinstance(path_value, str)
            or not isinstance(start, int)
            or isinstance(start, bool)
            or start < 1
            or not isinstance(start_column, int)
            or isinstance(start_column, bool)
            or start_column < 0
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
        if start > total:
            return tool_error("line_out_of_range", "Start line is beyond end of file.")
        if start_column > len(lines[start - 1]):
            return tool_error("column_out_of_range", "Start column is beyond end of line.")
        requested_end = end_value if end_value is not None else start + MAX_READ_LINES - 1
        actual_end = min(requested_end, total)
        numbered, char_cursor = _numbered_page(
            lines,
            start,
            actual_end,
            start_column,
        )
        more_lines = char_cursor is None and actual_end < total
        next_start_line = (
            char_cursor[0]
            if char_cursor is not None
            else actual_end + 1 if more_lines else None
        )
        data: dict[str, JSONValue] = {
            "path": path.relative_to(self.root).as_posix(),
            "start_line": start,
            "end_line": actual_end,
            "total_lines": total,
            "content": numbered,
            "truncated": more_lines or char_cursor is not None,
            "next_start_line": next_start_line,
        }
        if char_cursor is not None:
            data["next_start_column"] = char_cursor[1]
        return ToolResult(
            True,
            data,
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


class FindSymbolTool(BaseTool):
    name = "find_symbol"
    description = "Find indexed Python function, class, or method definitions by name."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Symbol name"}},
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, index: RepositoryIndex) -> None:
        self.index = index

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = _single_string(arguments, "name")
        if name is None:
            return _invalid_arguments()
        definitions = [asdict(item) for item in self.index.symbols_named(name)]
        return ToolResult(True, {"name": name, "definitions": definitions})


class FindReferencesTool(BaseTool):
    name = "find_references"
    description = (
        "Find possible AST references to a name; results are not LSP semantic guarantees."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Name to locate"}},
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path, index: RepositoryIndex) -> None:
        self.root = root
        self.index = index

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = _single_string(arguments, "name")
        if name is None:
            return _invalid_arguments()
        matches: list[dict[str, JSONValue]] = []
        for module in self.index.modules:
            if module.parse_error is not None:
                continue
            path = self.root / module.path
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=module.path)
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            lines = source.splitlines()
            seen_lines: set[int] = set()
            for node in ast.walk(tree):
                if not _node_references_name(node, name):
                    continue
                line_number = getattr(node, "lineno", 0)
                if line_number <= 0 or line_number in seen_lines:
                    continue
                seen_lines.add(line_number)
                matches.append(
                    {
                        "path": module.path,
                        "line": line_number,
                        "content": lines[line_number - 1][:500],
                    }
                )
        matches.sort(key=lambda item: (str(item["path"]), int(item["line"])))
        truncated = len(matches) > MAX_SEARCH_RESULTS
        return ToolResult(
            True,
            {
                "name": name,
                "references": matches[:MAX_SEARCH_RESULTS],
                "total_matches": len(matches),
                "truncated": truncated,
            },
        )


class InspectModuleTool(BaseTool):
    name = "inspect_module"
    description = "Inspect indexed symbols, imports, and parse status for a Python module."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Python file path"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, index: RepositoryIndex) -> None:
        self.index = index

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = _single_string(arguments, "path")
        if path is None:
            return _invalid_arguments()
        module = self.index.module_for_path(path)
        if module is None:
            return tool_error("module_not_found", "Python module was not indexed.")
        return ToolResult(
            True,
            {
                "path": module.path,
                "module": module.module,
                "symbols": [asdict(item) for item in module.symbols],
                "imports": [asdict(item) for item in module.imports],
                "parse_error": module.parse_error,
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
            with path.open(encoding="utf-8", newline="") as source:
                content = source.read()
        except UnicodeDecodeError:
            return tool_error("unsupported_text_file", "File is not valid UTF-8 text.")
        newline_pattern = r"\r\n|\r|\n"
        parts = (re.escape(part) for part in re.split(newline_pattern, old_text))
        # CRLF is one logical newline: never backtrack it into two matches.
        matches = list(re.finditer(r"(?>\r\n|\r|\n)".join(parts), content))
        count = len(matches)
        if count != 1:
            result = tool_error("expected_one_match", "Replacement text must match exactly once.")
            return ToolResult(result.ok, result.data, result.error, {"matches": count})
        match = matches[0]
        newline_match = re.search(newline_pattern, match.group()) or re.search(
            newline_pattern, content
        )
        newline = newline_match.group() if newline_match else "\n"
        replacement = re.sub(newline_pattern, newline, arguments["new_text"])
        updated = content[: match.start()] + replacement + content[match.end() :]
        path.write_text(updated, encoding="utf-8", newline="")
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

    def __init__(self, root: Path, runner: TestExecutor, target_node_id: str | None) -> None:
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
        runner: TestExecutor,
        target_node_id: str | None,
    ) -> None:
        self.session = session
        self.workspace = session.working
        self.index = build_repository_index(self.workspace)
        tools: tuple[BaseTool, ...] = (
            ReadFileTool(self.workspace),
            SearchCodeTool(self.workspace),
            FindSymbolTool(self.index),
            FindReferencesTool(self.workspace, self.index),
            InspectModuleTool(self.index),
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
        result = tool.execute(arguments)
        return ToolResult(
            result.ok,
            result.data,
            result.error,
            {**result.metadata, "trusted": False},
        )


def _numbered_page(
    lines: list[str],
    start_line: int,
    end_line: int,
    start_column: int,
) -> tuple[str, tuple[int, int] | None]:
    chunks: list[str] = []
    used = 0
    marker = "\n[TRUNCATED]"
    for line_number in range(start_line, end_line + 1):
        column = start_column if line_number == start_line else 0
        prefix = f"{line_number}: "
        separator = "\n" if chunks else ""
        text = lines[line_number - 1][column:]
        full = separator + prefix + text
        if used + len(full) <= MAX_READ_CHARS:
            chunks.append(full)
            used += len(full)
            continue

        available = MAX_READ_CHARS - used - len(separator) - len(prefix) - len(marker)
        consumed = max(0, available)
        fragment = separator + prefix + text[:consumed]
        if len(fragment) + used + len(marker) <= MAX_READ_CHARS:
            chunks.append(fragment + marker)
        return "".join(chunks), (line_number, column + consumed)
    return "".join(chunks), None


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


def _single_string(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if set(arguments) != {key} or not isinstance(value, str) or not value:
        return None
    return value


def _node_references_name(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    if isinstance(node, ast.alias):
        return node.name.rsplit(".", 1)[-1] == name or node.asname == name
    return False
