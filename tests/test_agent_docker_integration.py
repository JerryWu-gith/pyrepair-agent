"""Explicit no-model Docker validation, including text-only upstream gold calibration.

No upstream package is imported on the host. A reference patch is used only by
this offline controller, never supplied as model input or counted as Agent skill.
"""

import json
import os
from pathlib import Path

import pytest

from pyrepair.config import AppConfig
from pyrepair.models import RepairRequest
from pyrepair.pytest_parser import PytestParser
from tests.test_agent_test_runner import public_spec
from tests.test_agent_worker_docker import successful_client

pytestmark = pytest.mark.docker


def configured_lock():
    value = os.environ.get("PYREPAIR_DOCKER_ENVIRONMENT_LOCK")
    if not value:
        pytest.fail("explicit Docker environment lock required; no build or host fallback")
    return Path(value).absolute()


def make_owned_repo(tmp_path):
    repo = tmp_path / "public"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "TASK.md").write_text("Restore addition without changing tests.\n", encoding="utf-8")
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "test_owned.py").write_text(
        "from app import add\n"
        "def test_owned():\n    assert add(2, 3) == 5\n"
        "def test_environment():\n"
        "    import os\n"
        "    assert 'DEEPSEEK_API_KEY' not in os.environ\n"
        "    assert 'UNTRUSTED_SENTINEL' not in os.environ\n",
        encoding="utf-8",
    )
    return repo


def assert_clean_independent_stages(evidence, expected):
    records = [
        json.loads(p.read_text("utf-8"))
        for p in sorted(evidence.glob("test-*/adapter-result.json"))
    ]
    assert len(records) == expected
    assert all(r["status"] in {"passed", "failed"} for r in records)
    assert len({r["container_id"] for r in records}) == expected
    for record in records:
        file = Path(record["docker_artifacts"]) / "supervisor-result.json"
        data = json.loads(file.read_text("utf-8"))
        assert data["cleanup_errors"] == []
        assert data["integrity"]["unchanged"] is True


def test_real_agent_runner_returns_collection_failure_then_retests_edited_source(
    tmp_path, monkeypatch
):
    from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "worthless-owned-sentinel")
    monkeypatch.setenv("UNTRUSTED_SENTINEL", "worthless-owned-sentinel")
    repo = make_owned_repo(tmp_path)
    evidence = tmp_path / "execution"
    runner = DockerAgentTestRunner(configured_lock(), public_spec(repo), evidence)
    baseline = runner.run(repo)
    assert baseline.exit_code == 1
    target = PytestParser().parse(baseline).node_id
    assert target == "test_owned.py::test_owned"
    (repo / "app.py").write_text("def add(:\n", encoding="utf-8")
    broken = runner.run(repo, target)
    assert broken.exit_code == 4  # Precise-node import failure, not a missing selector.
    assert broken.failures[0].phase == "collection"
    assert broken.failures[0].exception_type == "SyntaxError"
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    assert runner.run(repo, target).exit_code == 0
    assert runner.run(repo).exit_code == 0
    assert_clean_independent_stages(evidence, 4)


def test_real_docker_fake_model_full_repair_never_invokes_host_runner(tmp_path, monkeypatch):
    from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner
    from benchmarks.evaluation.agent_worker import build_evaluation_coordinator, collect_result

    def forbidden(*args, **kwargs):
        raise AssertionError("host pytest is forbidden in Docker repair")

    repo = make_owned_repo(tmp_path)
    # A tiny fixture hides Windows whole-file LF->CRLF rewrites below Policy's limit.
    (repo / "app.py").write_bytes(b"# unchanged\n" * 200 + b"def add(a, b):\n    return a - b\n")
    original = (repo / "app.py").read_bytes()
    client = successful_client()
    monkeypatch.setattr("pyrepair.cli.DeepSeekClient", lambda **kwargs: client)
    monkeypatch.setattr("pyrepair.testing.TestRunner.run", forbidden)
    output = tmp_path / "repair"
    runner = DockerAgentTestRunner(configured_lock(), public_spec(repo), output / "tests")
    coordinator = build_evaluation_coordinator(
        AppConfig("worthless-owned-sentinel", "deepseek-flash"),
        output,
        runner=runner,
        record_usage=True,
    )
    assert coordinator.run(RepairRequest(repo)).status == "success"
    result = collect_result(output)
    assert result["status"] == "success"
    assert result["model_calls"] == {"repair": 4, "review": 1}
    assert result["usage_complete"] is True
    assert (repo / "app.py").read_bytes() == original
    patch_lines = (output / result["patch_path"]).read_text("utf-8").splitlines()
    assert [
        line for line in patch_lines if line.startswith("+") and not line.startswith("+++")
    ] == ["+    return a + b"]
    assert [
        line for line in patch_lines if line.startswith("-") and not line.startswith("---")
    ] == ["-    return a - b"]
    assert_clean_independent_stages(output / "tests", 4)


@pytest.mark.parametrize("case_id", ["os_more_seekable_1269", "os_boltons_addlist_458"])
def test_real_upstream_adapter_public_baseline_and_reference_patch_only(tmp_path, case_id):
    from benchmarks.evaluation.agent_input import prepare_agent_input, validate_public_input
    from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner
    from benchmarks.evaluation.cases import load_cases
    from benchmarks.evaluation.patching import apply_patch_checked

    root = Path(__file__).resolve().parents[1]
    cases = load_cases(root / "benchmarks/manifest_opensource_v2.json")
    case = next(c for c in cases if c.id == case_id)
    repo = tmp_path / "public"
    spec = prepare_agent_input(case, repo)
    validate_public_input(repo, spec)
    assert not (repo / "hidden_tests").exists()
    assert not (repo / ".omp").exists()
    evidence = tmp_path / "execution"
    runner = DockerAgentTestRunner(configured_lock(), spec, evidence)
    baseline = runner.run(repo)
    assert baseline.exit_code == 1
    target = PytestParser().parse(baseline).node_id
    assert target is not None and target.startswith("tests/test_pyrepair_repro.py::")
    # Trusted controller applies reference text; no model sees this calibration.
    apply_patch_checked(case, repo, case.gold_patch.read_text(encoding="utf-8"))
    assert runner.run(repo, target).exit_code == 0
    assert runner.run(repo).exit_code == 0
    assert_clean_independent_stages(evidence, 3)
