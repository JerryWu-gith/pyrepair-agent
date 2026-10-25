"""Evaluation-owned TestRun adapter. No upstream Python ever runs on the host."""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from pyrepair.models import PytestFailure, TestRun

from .agent_input import PublicTaskSpec, stage_public_snapshot
from .container_protocol import is_link, safe_path
from .docker_runner import DockerTestRunner, _write_json


class AgentExecutionError(RuntimeError):
    """Fatal execution boundary failure, not an invitation to ask the model again."""


_STACK_PATH = re.compile(
    r"""(?m)^(?P<prefix>[ \t]*(?:E[ \t]+)?(?:File ["'])?)/work/"""
    r"""(?P<file>[\w./-]+\.py)(?P<suffix>:\d+|["'], line \d+)"""
)


def _relative_stack(text: str) -> str:
    def replace(match: re.Match) -> str:
        try:
            safe_path(match["file"])
        except ValueError:
            return match[0]
        return match["prefix"] + match["file"] + match["suffix"]

    return _STACK_PATH.sub(replace, text)


class DockerAgentTestRunner:
    def __init__(self, environment_lock: Path, public_spec: PublicTaskSpec, output_root: Path):
        if not isinstance(public_spec, PublicTaskSpec):
            raise AgentExecutionError("validated public task descriptor required")
        self.public_spec = public_spec
        self.backend = DockerTestRunner(environment_lock)
        try:
            self.backend.assert_environment_verified()
        except (OSError, ValueError, RuntimeError) as exc:
            raise AgentExecutionError("verified Docker environment required") from exc
        self.output_root = Path(output_root).absolute()
        if any(is_link(p) for p in (self.output_root, *self.output_root.parents)):
            raise AgentExecutionError("linked Agent execution output")
        self.output_root.mkdir(parents=True, exist_ok=False)
        self._sequence = 0
        self._baseline_nodes: frozenset[str] | None = None
        self._targets: frozenset[str] = frozenset()

    def run(self, repo: Path, target: str | None = None) -> TestRun:
        if target is not None and (
            not isinstance(target, str)
            or self._baseline_nodes is None
            or target not in self._targets
        ):
            raise AgentExecutionError("target must be an exact failing node from this baseline")
        repo = Path(repo).absolute()
        if self.output_root.resolve().is_relative_to(
            repo.resolve()
        ) or repo.resolve().is_relative_to(self.output_root.resolve()):
            raise AgentExecutionError("Agent output and input roots overlap")
        self._sequence += 1
        # Keep evidence paths compact on Windows with LongPathsEnabled=0.
        # The full protocol UUIDs/container IDs remain unchanged; mkdir is exclusive.
        stage = self.output_root / f"test-{self._sequence:04d}-{uuid.uuid4().hex[:12]}"
        stage.mkdir()
        started = time.monotonic()
        result = None
        try:
            selection = stage_public_snapshot(repo, stage / "repo", self.public_spec.visible_tests)
            _write_json(stage / "selection.json", {**selection, "target": target})
            result = self.backend.run_agent(
                stage / "repo",
                self.public_spec.visible_tests,
                stage / "p.log",
                self.public_spec.timeout_seconds,
                target=target,
            )
            if (
                result.get("status") not in ("passed", "failed")
                or result.get("cleanup_errors") != []
            ):
                raise AgentExecutionError(
                    f"container execution failed ({result.get('status')}); evidence={stage}"
                )
            probe = result["probe"]
            nodes = frozenset(probe["collected"])
            if target is None:
                if self._baseline_nodes is None:
                    self._baseline_nodes = nodes
                    self._targets = frozenset(
                        row["node_id"] for row in result["failures"] if row["phase"] != "collection"
                    )
                elif not probe["collection_errors"] and nodes != self._baseline_nodes:
                    raise AgentExecutionError(
                        f"public collection coverage differs from baseline; evidence={stage}"
                    )
            failures = tuple(
                PytestFailure(**{**row, "traceback": _relative_stack(row["traceback"])})
                for row in result["failures"]
            )
            elapsed = int((time.monotonic() - started) * 1000)
            command = (
                "container-pytest",
                *(self.public_spec.visible_tests if target is None else (target,)),
            )
            log = (stage / "p.log").read_text(encoding="utf-8", errors="replace")
            _write_json(
                stage / "adapter-result.json",
                {
                    "status": result["status"],
                    "pytest_exit_code": result["returncode"],
                    "duration_ms": elapsed,
                    "container_id": result["container_id"],
                    "identity": result["identity"],
                    "docker_artifacts": result["artifacts"],
                    "public_input_hash": selection["public_input_hash"],
                    "output_semantics": "validated_combined_pytest_log",
                },
            )
            return TestRun(
                command=command,
                exit_code=result["returncode"],
                stdout=log,
                stderr="",
                duration_ms=elapsed,
                failures=failures,
                capture_source="plugin",
            )
        except (OSError, ValueError, TypeError, KeyError, AgentExecutionError) as exc:
            evidence = {
                "status": "execution_error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:2000],
                "duration_ms": int((time.monotonic() - started) * 1000),
                "supervisor_status": result.get("status") if isinstance(result, dict) else None,
            }
            try:
                _write_json(stage / "adapter-result.json", evidence)
            except OSError as write_error:
                exc.add_note(f"execution evidence write failed: {type(write_error).__name__}")
            if isinstance(exc, AgentExecutionError):
                raise
            raise AgentExecutionError(f"Agent test execution failed; evidence={stage}") from exc
