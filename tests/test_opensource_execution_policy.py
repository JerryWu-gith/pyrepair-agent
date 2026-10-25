"""Fail closed before any host test or paid worker can start.

All fixtures here are our own tiny addition example, even when their metadata
is deliberately tagged 'opensource'. No upstream code is executed by RED tests.
"""

from dataclasses import replace

import pytest

from benchmarks.evaluation.cases import load_cases
from tests.evaluation_helpers import change_manifest, make_case
from tests.test_evaluation_cli import run


@pytest.fixture
def case(tmp_path):
    return replace(load_cases(make_case(tmp_path / "bank"))[0], source_kind="opensource")


def forbidden(*args, **kwargs):
    raise AssertionError("execution/config/credential boundary must not be reached")


@pytest.mark.parametrize("source_kind", ["opensource", "unknown"])
def test_host_validation_refuses_before_output_or_process(case, tmp_path, monkeypatch, source_kind):
    from benchmarks.evaluation import grading

    case = replace(case, source_kind=source_kind)
    output = tmp_path / "validation"
    monkeypatch.setattr(grading, "execute", forbidden)
    with pytest.raises(ValueError, match=source_kind):
        grading.validate_case(case, output)
    assert not output.exists()


@pytest.mark.parametrize("empty", [False, True])
def test_grade_refuses_before_creating_output_even_without_patch(
    case, tmp_path, monkeypatch, empty
):
    from benchmarks.evaluation import grading

    output = tmp_path / "grade"
    monkeypatch.setattr(grading, "execute", forbidden)
    patch = "" if empty else case.gold_patch.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="opensource"):
        grading.grade_patch(case, patch, output)
    assert not output.exists()


def test_injected_runner_does_not_bypass_host_policy(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    output = tmp_path / "grade"
    with pytest.raises(ValueError, match="opensource"):
        grade_patch(case, case.gold_patch.read_text(), output, test_runner=forbidden)
    assert not output.exists()


@pytest.mark.parametrize("mixed", [False, True])
def test_create_refuses_before_identity_or_validation(case, tmp_path, monkeypatch, mixed):
    from benchmarks.evaluation import experiment

    cases = ([replace(case, id="local", source_kind="synthetic")] if mixed else []) + [case]
    output = tmp_path / "experiment"
    monkeypatch.setattr(experiment, "_identity", forbidden)
    with pytest.raises(ValueError, match="opensource"):
        experiment.create_experiment(cases, output, "deepseek-flash", 1)
    assert not output.exists()


def test_resume_refuses_before_reading_config_or_starting_worker(case, tmp_path, monkeypatch):
    from benchmarks.evaluation import experiment

    output = tmp_path / "missing-experiment"
    monkeypatch.setattr(experiment, "load_config", forbidden)
    with pytest.raises(ValueError, match="opensource"):
        experiment.run_experiment(output, [case], agent_executor=forbidden)
    assert not output.exists()


def test_agent_refuses_before_environment_and_credentials(case, tmp_path, monkeypatch):
    from benchmarks.evaluation import agent_worker

    output = tmp_path / "agent"
    monkeypatch.setattr(agent_worker, "clean_environment", forbidden)
    with pytest.raises(ValueError, match="opensource"):
        agent_worker.run_agent(case, output, "deepseek-flash")
    assert not output.exists()


@pytest.mark.parametrize("command", ["validate", "grade", "run", "resume"])
def test_cli_refuses_before_outputs_patch_reads_or_key_check(tmp_path, command):
    manifest = make_case(tmp_path / "bank")
    change_manifest(manifest, source_kind="opensource")
    output = tmp_path / "output"
    args = [command if command != "resume" else "run", "--manifest", manifest, "--case", "demo"]
    if command == "resume":
        args += ["--resume", output]
    else:
        args += ["--output", output]
    if command == "grade":
        # Policy failure must precede a missing patch file error.
        args += ["--patch", tmp_path / "missing.patch"]
    result = run(*args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "source_kind=opensource" in result.stderr, result.stderr
    assert "DEEPSEEK_API_KEY" not in result.stderr
    assert not output.exists()


def test_policy_allows_synthetic_and_checks_entire_iterable(case):
    from benchmarks.evaluation.execution_policy import require_host_case, require_live_cases

    synthetic = replace(case, source_kind="synthetic")
    require_host_case(synthetic)
    require_live_cases(iter([synthetic]))
    with pytest.raises(ValueError, match="opensource"):
        require_live_cases(iter([synthetic, case]))
    with pytest.raises(ValueError, match="unknown"):
        require_live_cases([replace(case, source_kind="unknown")])


def test_opensource_policy_rejects_missing_and_boolean_backends(case):
    from benchmarks.evaluation.execution_policy import require_case_backend

    with pytest.raises(ValueError, match="verified Docker"):
        require_case_backend(case, "synthetic", forbidden)
    with pytest.raises(ValueError, match="DockerTestRunner"):
        require_case_backend(case, "docker", type("Pretender", (), {"is_sandbox": True})())


def test_opensource_policy_requires_concrete_runner_environment_evidence(case, tmp_path):
    from benchmarks.evaluation.docker_runner import DockerTestRunner
    from benchmarks.evaluation.execution_policy import require_case_backend

    runner = DockerTestRunner(tmp_path / "missing-lock.json")
    with pytest.raises(ValueError, match="environment lock|evidence|Docker"):
        require_case_backend(case, "docker", runner)


def test_opensource_policy_accepts_verified_docker_and_synthetic_wrappers(case, monkeypatch):
    from benchmarks.evaluation.docker_runner import DockerTestRunner
    from benchmarks.evaluation.execution_policy import require_case_backend

    runner = DockerTestRunner.__new__(DockerTestRunner)
    monkeypatch.setattr(
        DockerTestRunner,
        "assert_environment_verified",
        lambda self: {"backend": "docker", "image_id": "sha256:" + "a" * 64},
    )
    require_case_backend(case, "docker", runner)
    require_case_backend(replace(case, source_kind="synthetic"), "synthetic", forbidden)


@pytest.mark.parametrize("mismatch", ["lock_hash", "image_id"])
def test_opensource_policy_rejects_lock_or_image_mismatch(case, tmp_path, monkeypatch, mismatch):
    from benchmarks.evaluation import docker_runner
    from benchmarks.evaluation.docker_runner import DockerTestRunner
    from benchmarks.evaluation.execution_policy import require_case_backend

    runner = DockerTestRunner(tmp_path / "environment.lock")
    image_id = "sha256:" + "a" * 64
    check = {
        "version": 1,
        "status": "environment_verified",
        "lock_hash": "current-lock-hash",
        "image_id": image_id,
        "checks": {name: True for name in docker_runner.CHECKS},
    }
    if mismatch == "lock_hash":
        check["lock_hash"] = "old-lock-hash"
    else:
        check["image_id"] = "sha256:" + "b" * 64
    monkeypatch.setattr(docker_runner, "_load_lock", lambda path: {"image_id": image_id})
    monkeypatch.setattr(docker_runner, "_read_evidence", lambda path: check)
    monkeypatch.setattr(docker_runner, "_hash", lambda path: "current-lock-hash")
    monkeypatch.setattr(docker_runner, "_engine", forbidden)

    with pytest.raises(ValueError, match="Docker environment"):
        require_case_backend(case, "docker", runner)
