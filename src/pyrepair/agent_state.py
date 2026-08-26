from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .models import AgentStatus
from .tools import ToolResult


@dataclass(frozen=True)
class ToolProgress:
    call_fingerprint: str
    result_fingerprint: str
    progressed: bool
    error_code: str | None


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def call_fingerprint(name: str, arguments: dict[str, Any]) -> str:
    return canonical_json({"name": name, "arguments": arguments})


class AgentRuntimeState:
    def __init__(self, attempt: int, max_attempts: int, max_tool_calls: int) -> None:
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.max_tool_calls = max_tool_calls
        self.tool_calls_used = 0
        self.files_read: set[str] = set()
        self.changed_files: set[str] = set()
        self.last_tool: str | None = None
        self.last_error: str | None = None
        self.last_call_fingerprint: str | None = None
        self.repeated_call_count = 0
        self.no_progress_steps = 0
        self.diff_inspected = False
        self.target_test_run = False
        self._seen_results: set[tuple[str, str]] = set()
        self._error_counts: dict[tuple[str, str], int] = {}

    def record_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        result: ToolResult,
    ) -> ToolProgress:
        call_key = call_fingerprint(name, arguments)
        result_key = canonical_json(_stable_result(name, result))
        pair = (call_key, result_key)
        progressed = pair not in self._seen_results
        self._seen_results.add(pair)

        self.tool_calls_used += 1
        self.last_tool = name
        if call_key == self.last_call_fingerprint:
            self.repeated_call_count += 1
        else:
            self.repeated_call_count = 1
        self.last_call_fingerprint = call_key

        error_code = result.error.code if result.error else None
        self.last_error = error_code
        if error_code is not None:
            error_key = (call_key, error_code)
            self._error_counts[error_key] = self._error_counts.get(error_key, 0) + 1

        if progressed:
            self.no_progress_steps = 0
        else:
            self.no_progress_steps += 1

        if result.ok:
            self._record_success(name, result)

        return ToolProgress(call_key, result_key, progressed, error_code)

    def identical_error_count(self, fingerprint: str) -> int:
        return max(
            (
                count
                for (call_key, _error_code), count in self._error_counts.items()
                if call_key == fingerprint
            ),
            default=0,
        )

    def snapshot(self) -> AgentStatus:
        return AgentStatus(
            attempt=self.attempt,
            max_attempts=self.max_attempts,
            tool_calls_used=self.tool_calls_used,
            max_tool_calls=self.max_tool_calls,
            files_read=tuple(sorted(self.files_read)),
            changed_files=tuple(sorted(self.changed_files)),
            last_tool=self.last_tool,
            last_error=self.last_error,
            repeated_call_count=self.repeated_call_count,
            no_progress_steps=self.no_progress_steps,
            diff_inspected=self.diff_inspected,
            target_test_run=self.target_test_run,
        )

    def _record_success(self, name: str, result: ToolResult) -> None:
        if name in {"read_file", "inspect_module"}:
            path = result.data.get("path")
            if isinstance(path, str):
                self.files_read.add(path)
        elif name == "replace_text":
            path = result.data.get("path")
            if isinstance(path, str):
                self.changed_files.add(path)
            self.diff_inspected = False
            self.target_test_run = False
        elif name == "show_diff":
            self.diff_inspected = True
        elif name == "run_target_test":
            self.target_test_run = True


def _stable_result(name: str, result: ToolResult) -> dict[str, object]:
    payload = asdict(result)
    if name != "run_target_test":
        return payload

    stable_keys = ("target", "passed", "exit_code", "timed_out")
    payload["data"] = {
        key: result.data[key]
        for key in stable_keys
        if key in result.data
    }
    return payload
