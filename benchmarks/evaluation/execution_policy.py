"""Execution gates for case-aware evaluation entry points.

Source metadata is an allowlist, not an OS sandbox or a proof of trusted code.
Opensource grading is permitted only through the concrete, independently
verified Docker runner. Live opensource execution remains out of scope.
"""

import subprocess
from collections.abc import Iterable

from .cases import EvaluationCase


def require_host_case(case: EvaluationCase) -> None:
    if case.source_kind != "synthetic":
        raise ValueError(
            f"source_kind={case.source_kind}: host evaluation is disabled; "
            "opensource tasks require a verified Docker backend (not connected yet)"
        )


def require_case_backend(case: EvaluationCase, backend: str, test_runner) -> None:
    """Enforce the selected offline backend before any grader output is created."""
    if backend not in {"synthetic", "docker"}:
        raise ValueError(f"unsupported grading backend: {backend}")
    if backend == "synthetic":
        if case.source_kind != "synthetic":
            raise ValueError(
                f"source_kind={case.source_kind}: opensource cases require the verified Docker backend"
            )
        return

    if case.source_kind not in {"synthetic", "opensource"}:
        raise ValueError(f"source_kind={case.source_kind}: unsupported case source")
    from .docker_runner import DockerTestRunner

    if type(test_runner) is not DockerTestRunner:
        raise ValueError(
            f"source_kind={case.source_kind}: verified Docker backend requires the concrete DockerTestRunner"
        )
    try:
        DockerTestRunner.assert_environment_verified(test_runner)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        raise ValueError(f"verified Docker environment required: {exc}") from exc


def require_live_cases(cases: Iterable[EvaluationCase]) -> None:
    for case in cases:
        if case.source_kind != "synthetic":
            raise ValueError(
                f"source_kind={case.source_kind}: live evaluation is disabled; "
                "opensource pilot is offline-only"
            )
