"""Opt-in owned probes only. Never builds/pulls or imports an upstream tree."""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker


def test_real_docker_owned_security_and_timeout_probes(tmp_path):
    from benchmarks.evaluation.docker_runner import check_environment

    configured = os.environ.get("PYREPAIR_DOCKER_ENVIRONMENT_LOCK")
    if not configured:
        pytest.fail(
            "Docker integration not executed: set PYREPAIR_DOCKER_ENVIRONMENT_LOCK to a prepared lock"
        )
    lock = tmp_path / "environment-lock.json"
    lock.write_bytes(Path(configured).absolute().read_bytes())
    result = check_environment(lock, tmp_path / "environment-check.json")
    assert result["status"] == "environment_verified", result
    assert result["checks"] == {
        "non_root": True,
        "readonly_root": True,
        "readonly_input": True,
        "credentials_absent": True,
        "external_network_blocked": True,
        "loopback_available": True,
        "seccomp_active": True,
        "profile_inspected": True,
        "timeout_stopped": True,
    }
