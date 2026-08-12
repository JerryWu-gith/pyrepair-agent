from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from .models import TestRun


class TestRunner:
    def __init__(self, timeout_seconds: float = 120.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, repo: Path, target: str | None = None) -> TestRun:
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--disable-warnings",
        ]
        if target:
            command.append(target)

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return TestRun(
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=int((time.perf_counter() - started) * 1000),
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
