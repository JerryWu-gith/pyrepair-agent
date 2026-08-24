from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar

from .testing import TestRunner
from .workspace import WorkspaceError, WorkspaceSession

MAX_READ_CHARS = 20_000
MAX_SEARCH_RESULTS = 50
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


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str = ""
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


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
        raise NotImplementedError  #抽象方法，子类必须自己实现，基类里抛 NotImplementedError 兜底


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a UTF-8 text file inside the temporary repair workspace."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Workspace-relative path"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if set(arguments) != {"path"} or not isinstance(arguments.get("path"), str):  #参数键必须是 "path"，值必须是字符串
            return ToolResult(False, error="invalid_arguments")
        try:
            path = resolve_inside(self.root, arguments["path"])
        except ToolError as exc:
            return ToolResult(False, error=str(exc))
        if not path.is_file():
            return ToolResult(False, error="file_not_found")
        if path.suffix.lower() not in READABLE_SUFFIXES:
            return ToolResult(False, error="unsupported_text_file")
        try:
            content = path.read_text(encoding="utf-8")  # Read file
        except UnicodeDecodeError:
            return ToolResult(False, error="unsupported_text_file")
        if len(content) > MAX_READ_CHARS:
            marker = "\n[TRUNCATED]"
            content = content[: MAX_READ_CHARS - len(marker)] + marker
        return ToolResult(True, content=content)


class SearchCodeTool(BaseTool):
    name = "search_code"
    description = "Search for literal text in Python source files inside the workspace."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Literal text to find"}},
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if set(arguments) != {"query"} or not isinstance(query, str) or not query:
            return ToolResult(False, error="invalid_arguments")
        matches: list[str] = []
        for path in sorted(self.root.rglob("*.py")):   # 遍历所有 py 文件
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            relative = path.relative_to(self.root).as_posix()
            for line_number, line in enumerate(lines, start=1):
                if query not in line:
                    continue
                matches.append(f"{relative}:{line_number}:{line}")
                if len(matches) == MAX_SEARCH_RESULTS:
                    return ToolResult(True, content="\n".join(matches))
        return ToolResult(True, content="\n".join(matches))


class ReplaceTextTool(BaseTool):
    name = "replace_text"
    description = "Replace text that appears exactly once in a Python source file."
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
            return ToolResult(False, error="invalid_arguments")
        old_text = arguments["old_text"]
        if not old_text:
            return ToolResult(False, error="invalid_arguments")
        try:
            path = resolve_inside(self.root, arguments["path"])
        except ToolError as exc:
            return ToolResult(False, error=str(exc))
        relative = path.relative_to(self.root)
        if any(part.lower() == "tests" for part in relative.parts):
            return ToolResult(False, error="protected_test_path")
        if path.suffix.lower() not in {".py", ".pyi"}:
            return ToolResult(False, error="source_files_only")
        if not path.is_file():
            return ToolResult(False, error="file_not_found")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(False, error="unsupported_text_file")
        count = content.count(old_text)
        if count != 1:
            return ToolResult(False, error=f"expected_one_match_found_{count}")
        path.write_text(content.replace(old_text, arguments["new_text"], 1), encoding="utf-8")
        return ToolResult(True, content=f"replaced:{relative.as_posix()}")


class ShowDiffTool(BaseTool):
    name = "show_diff"
    description = "Show the current candidate unified diff."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, session: WorkspaceSession) -> None:
        self.session = session

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if arguments:
            return ToolResult(False, error="invalid_arguments")
        try:
            return ToolResult(True, content=self.session.snapshot().text)
        except WorkspaceError as exc:
            return ToolResult(False, error=f"diff_unavailable:{exc}")


class RunTargetTestTool(BaseTool):
    name = "run_target_test"
    description = "Run only the pytest node id identified from the original failure."
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
            return ToolResult(False, error="invalid_arguments")
        if not self.target_node_id:
            return ToolResult(False, error="target_test_unavailable")
        run = self.runner.run(self.root, self.target_node_id)
        if run.timed_out:
            return ToolResult(False, error="target_test_timeout")
        if run.launch_error:
            return ToolResult(False, error=f"target_test_launch_error:{run.launch_error}")
        return ToolResult(
            True,
            content=json.dumps(
                {
                    "target": self.target_node_id,
                    "exit_code": run.exit_code,
                    "stdout": run.stdout,
                    "stderr": run.stderr,
                    "duration_ms": run.duration_ms,
                },
                ensure_ascii=False,
            ),
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
            return ToolResult(False, error="unknown_tool")
        if not isinstance(arguments, dict):
            return ToolResult(False, error="invalid_arguments")
        return tool.execute(arguments)


def resolve_inside(root: Path, user_path: str) -> Path:
    candidate = (root / user_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ToolError("path_outside_workspace") from exc
    return candidate
