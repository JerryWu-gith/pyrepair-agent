from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import PatchSnapshot, TestRun

SAFE_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "token",
    "secret",
    "deepseek_api_key",
}


class RecorderError(RuntimeError):
    """Raised when repair artifacts cannot be recorded safely."""


class RunRecorder:
    def __init__(
        self,
        repo: Path,
        run_id: str | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        selected_run_id = _new_run_id() if run_id is None else run_id
        if not SAFE_RUN_ID_RE.fullmatch(selected_run_id):
            raise RecorderError("run-id 只能包含字母、数字、点、下划线和连字符")
        self.sensitive_values = tuple(value for value in sensitive_values if value)
        self.run_dir = repo.resolve() / ".pyrepair" / "runs" / selected_run_id
        try:
            self.run_dir.mkdir(parents=True, exist_ok=False)
            _atomic_write(self.run_dir / "fix.patch", "")
            _atomic_write(self.run_dir / "report.json", "{}\n")
            _atomic_write(self.run_dir / "trace.jsonl", "")
            _atomic_write(self.run_dir / "pytest.log", "")
        except OSError as exc:
            raise RecorderError(f"创建运行产物目录失败：{exc}") from exc

    def write_patch(self, snapshot: PatchSnapshot) -> None:
        _atomic_write(
            self.run_dir / "fix.patch",
            self._redact(snapshot.text),
        )

    def write_report(self, report: Any) -> None:
        safe = self._redact(_jsonable(report))
        text = json.dumps(safe, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(self.run_dir / "report.json", text)

    def append_event(self, event: dict[str, Any]) -> None:
        path = self.run_dir / "trace.jsonl"
        safe = self._redact(_jsonable(event))
        line = json.dumps(safe, ensure_ascii=False) + "\n"
        _atomic_write(path, path.read_text(encoding="utf-8") + line)

    def append_pytest(self, section: str, run: TestRun) -> None:
        path = self.run_dir / "pytest.log"
        command = " ".join(run.command)
        block = (
            f"===== {section} =====\n"
            f"command: {command}\n"
            f"exit_code: {run.exit_code}\n"
            f"duration_ms: {run.duration_ms}\n"
            f"timed_out: {run.timed_out}\n"
            f"launch_error: {run.launch_error or ''}\n"
            "--- stdout ---\n"
            f"{run.stdout}\n"
            "--- stderr ---\n"
            f"{run.stderr}\n\n"
        )
        _atomic_write(path, path.read_text(encoding="utf-8") + self._redact(block))

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    "[REDACTED]"
                    if str(key).lower() in SENSITIVE_KEYS
                    else self._redact(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            redacted = value
            for secret in self.sensitive_values:
                redacted = redacted.replace(secret, "[REDACTED]")
            return redacted
        return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_jsonable(item) for item in sorted(value, key=str)]
    return value


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="")
        temporary.replace(path)
    except OSError as exc:
        raise RecorderError(f"写入运行产物失败：{path.name}: {exc}") from exc


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"
