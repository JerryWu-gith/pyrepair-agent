"""Exercise the real adapter and supervisor; replace only external Docker calls."""

import hashlib
import json
import os

import pytest

from tests.test_docker_runner import (
    setup_backend as setup_backend,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_docker_runner import write_json

NODE = "test_owned.py::test_owned"


def public_spec(repo):
    from benchmarks.evaluation.agent_input import PublicTaskSpec
    from benchmarks.evaluation.container_protocol import input_inventory, inventory_hash

    return PublicTaskSpec.from_dict(
        {
            "version": 1,
            "case_id": "owned",
            "revision": 1,
            "source_kind": "opensource",
            "visible_tests": ["test_owned.py"],
            "timeout_seconds": 10,
            "input_policy": "agent-public-r2",
            "public_input_hash": inventory_hash(input_inventory(repo, ("test_owned.py",))),
        }
    )


def fail_calls(fake):
    fake.exit_code = 1

    def mutation(output, result):
        probe = result["probe"]
        probe["exit_code"] = result["pytest_returncode"] = 1
        probe["reports"][1].update(outcome="failed", exception_type="AssertionError")
        probe["failures"] = [
            {
                "node_id": NODE,
                "phase": "call",
                "outcome": "failed",
                "exception_type": "AssertionError",
                "summary": "assert 1 == 2",
                "traceback": '/work/app.py:2: AssertionError\n    assert "/work/app.py" == value',
                "duration_ms": 2,
            }
        ]
        write_json(output / "probe.json", probe)
        write_json(output / "result.json", result)
        (output / "pytest.log").write_text("owned assertion failed\n", encoding="utf-8")

    fake.mutate_output = mutation


def test_adapter_uses_fresh_filtered_snapshots_for_baseline_target_and_full(setup_backend):
    from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner

    _, fake, lock, repo, _ = setup_backend
    (repo / "app.py").write_bytes(b"value = 1\n")
    (repo / ".pyrepair/internal").mkdir(parents=True)
    (repo / ".pyrepair/internal/old.json").write_text("excluded-owned-sentinel")
    evidence = lock.parent / "agent-tests"
    runner = DockerAgentTestRunner(lock, public_spec(repo), evidence)
    fail_calls(fake)

    baseline = runner.run(repo)

    assert baseline.exit_code == 1
    assert baseline.capture_source == "plugin"
    assert baseline.failures[0].node_id == NODE
    assert baseline.failures[0].traceback.startswith("app.py:2:")
    assert 'assert "/work/app.py" == value' in baseline.failures[0].traceback
    (repo / "app.py").write_bytes(b"value = 2\n")
    fake.exit_code = 0
    fake.mutate_output = lambda output, result: None
    target, full = runner.run(repo, NODE), runner.run(repo)

    assert target.exit_code == full.exit_code == 0
    assert target.command == ("container-pytest", NODE)
    assert full.command == ("container-pytest", "test_owned.py")
    stages = sorted(evidence.glob("test-*/selection.json"))
    assert len(stages) == 3
    selections = [json.loads(path.read_text("utf-8")) for path in stages]
    assert selections[0]["inventory"]["app.py"] == hashlib.sha256(b"value = 1\n").hexdigest()
    assert selections[1]["inventory"]["app.py"] == hashlib.sha256(b"value = 2\n").hexdigest()
    assert all(".pyrepair" not in str(s["inventory"]) for s in selections)
    assert sum(command[1] == "create" for command in fake.commands) == 3
    assert sum(command[1] == "rm" for command in fake.commands) == 3
    assert (repo / "app.py").read_bytes() == b"value = 2\n"


@pytest.mark.parametrize("target", [NODE, "outside.py::test_hidden", "-p", "../test.py::test_x"])
def test_adapter_rejects_target_before_any_baseline_without_launching_docker(setup_backend, target):
    from benchmarks.evaluation.agent_test_runner import AgentExecutionError, DockerAgentTestRunner

    _, fake, lock, repo, _ = setup_backend
    runner = DockerAgentTestRunner(lock, public_spec(repo), lock.parent / "agent-tests")

    with pytest.raises(AgentExecutionError, match="baseline|target"):
        runner.run(repo, target)
    assert not any(c[1] == "create" for c in fake.commands)


def test_adapter_rejects_a_passing_baseline_node_as_repair_target(setup_backend):
    from benchmarks.evaluation.agent_test_runner import AgentExecutionError, DockerAgentTestRunner

    _, _, lock, repo, _ = setup_backend
    runner = DockerAgentTestRunner(lock, public_spec(repo), lock.parent / "agent-tests")
    assert runner.run(repo).exit_code == 0
    with pytest.raises(AgentExecutionError, match="baseline|target"):
        runner.run(repo, NODE)


def test_adapter_never_claims_full_success_after_baseline_node_disappears(setup_backend):
    from benchmarks.evaluation.agent_test_runner import AgentExecutionError, DockerAgentTestRunner

    _, fake, lock, repo, _ = setup_backend
    runner = DockerAgentTestRunner(lock, public_spec(repo), lock.parent / "agent-tests")
    fail_calls(fake)
    runner.run(repo)
    fake.exit_code = 0

    def different_node(output, result):
        probe = result["probe"]
        probe["collected"] = ["test_owned.py::test_other"]
        for row in probe["reports"]:
            row["nodeid"] = "test_owned.py::test_other"
        write_json(output / "probe.json", probe)
        write_json(output / "result.json", result)

    fake.mutate_output = different_node
    with pytest.raises(AgentExecutionError, match="coverage|collection|baseline"):
        runner.run(repo)


@pytest.mark.parametrize("problem", ["create", "oom", "rm"])
def test_adapter_stops_on_execution_error_without_host_fallback(
    setup_backend, monkeypatch, problem
):
    from benchmarks.evaluation.agent_test_runner import AgentExecutionError, DockerAgentTestRunner

    def forbidden(*args, **kwargs):
        raise AssertionError("host fallback is forbidden")

    monkeypatch.setattr("pyrepair.testing.TestRunner.run", forbidden)
    _, fake, lock, repo, _ = setup_backend
    fake.problem = problem
    runner = DockerAgentTestRunner(lock, public_spec(repo), lock.parent / "agent-tests")
    with pytest.raises(AgentExecutionError):
        runner.run(repo)
    assert len(list((lock.parent / "agent-tests").glob("test-*/adapter-result.json"))) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows legacy path budget")
def test_adapter_compact_staging_accepts_upstream_style_nested_document(setup_backend):
    from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner

    _, _, lock, repo, _ = setup_backend
    document = repo / ".github/ISSUE_TEMPLATE/propose-a-new-itertool.md"
    document.parent.mkdir(parents=True)
    document.write_text("self-authored document, never executed", encoding="utf-8")
    evidence = lock.parent / "execution"
    runner = DockerAgentTestRunner(lock, public_spec(repo), evidence)

    assert runner.run(repo).exit_code == 0
