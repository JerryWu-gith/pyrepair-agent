from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .models import TestRun
from .pytest_capture import CaptureReportError, load_capture_report
from .pytest_parser import parse_text_failures


class TestRunner:
    def __init__(self, timeout_seconds: float = 120.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, repo: Path, target: str | None = None) -> TestRun:
        command = [
            sys.executable,  # 当前 Python 解释器
            "-m",    # 以模块方式运行 pytest
            "pytest",
            "-q",   # quiet，精简输出
            "--tb=short",   # 短 traceback
            "--disable-warnings",  # 关掉警告刷屏
        ]
        if target:
            command.append(target)
        command.extend(["-p", "_pyrepair_agent_internal.pytest_plugin"])

        report_path = repo / ".pyrepair" / "internal" / "pytest-report.json"
        report_is_fresh = False
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        else:
            report_is_fresh = True
        environment = os.environ.copy()
        environment["PYREPAIR_PYTEST_REPORT"] = str(report_path)

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if report_is_fresh:
                try:
                    failures = load_capture_report(report_path)
                    capture_source = "plugin"
                except CaptureReportError:
                    report_is_fresh = False
            if not report_is_fresh:
                raw = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
                failures = parse_text_failures(raw)
                capture_source = "text" if failures else "none"
            return TestRun(
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=int((time.perf_counter() - started) * 1000),
                failures=failures,
                capture_source=capture_source,
            )
        except subprocess.TimeoutExpired as exc:
            return TestRun(
                command=tuple(command),
                exit_code=None,
                stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                stderr=exc.stderr if isinstance(exc.stderr, str) else "",
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )
        except OSError as exc:
            return TestRun(
                command=tuple(command),
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=int((time.perf_counter() - started) * 1000),
                launch_error=str(exc),
            )
