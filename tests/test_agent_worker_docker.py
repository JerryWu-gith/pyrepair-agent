"""Full real Agent components with FakeLLM and an external-only Docker boundary."""

import json
from dataclasses import replace

import pytest

from pyrepair.config import AppConfig
from pyrepair.models import RepairRequest
from tests.fakes import FakeLLM, model_text_turn, model_tool_turn
from tests.test_agent_test_runner import fail_calls, public_spec
from tests.test_docker_runner import (
    setup_backend as setup_backend,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_docker_runner import write_json


def successful_client():
    turns = [
        model_tool_turn(
            "replace",
            "replace_text",
            {
                "path": "app.py",
                "old_text": "return a - b",
                "new_text": "return a + b",
            },
        ),
        model_tool_turn("diff", "show_diff", {}),
        model_tool_turn("test", "run_target_test", {}),
        model_text_turn("completed"),
        model_text_turn(
            json.dumps({"approved": True, "risk": "low", "findings": [], "reason": "minimal fix"})
        ),
    ]
    return FakeLLM([replace(turn, prompt_tokens=7, completion_tokens=3) for turn in turns])


def test_fake_model_repair_reaches_all_docker_paths_and_exports_patch(setup_backend, monkeypatch):
    from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner
    from benchmarks.evaluation.agent_worker import build_evaluation_coordinator, collect_result

    _, fake, lock, repo, _ = setup_backend
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "TASK.md").write_text("Restore addition without changing tests.\n", encoding="utf-8")
    original = (repo / "app.py").read_bytes()
    client = successful_client()
    monkeypatch.setattr("pyrepair.cli.DeepSeekClient", lambda **kwargs: client)

    def forbidden(*args, **kwargs):
        raise AssertionError("host pytest fallback")

    monkeypatch.setattr("pyrepair.testing.TestRunner.run", forbidden)
    fail_calls(fake)
    fail_original = fake.mutate_output

    def stateful_tests(output, result):
        staged_app = fake.mounts["/input"] / "repo/app.py"
        if "return a - b" in staged_app.read_text("utf-8"):
            fake.exit_code = 1
            fail_original(output, result)
        else:
            fake.exit_code = 0

    fake.mutate_output = stateful_tests
    output = lock.parent / "repair-output"
    runner = DockerAgentTestRunner(lock, public_spec(repo), output / "tests")
    coordinator = build_evaluation_coordinator(
        AppConfig("offline-only-sentinel", "deepseek-flash"),
        output,
        runner=runner,
        record_usage=True,
    )
    repaired = coordinator.run(RepairRequest(repo))
    result = collect_result(output)

    assert repaired.status == result["status"] == "success"
    assert "+    return a + b" in (output / result["patch_path"]).read_text("utf-8")
    assert (repo / "app.py").read_bytes() == original
    assert result["model_calls"] == {"repair": 4, "review": 1}
    assert result["usage"]["repair"]["prompt_tokens"] == 28
    assert result["usage"]["review"]["completion_tokens"] == 3
    assert result["usage_complete"] is True
    assert sum(c[1] == "create" for c in fake.commands) == 4
    assert "hidden_tests" not in str(client.requests)


def test_tool_execution_crash_stops_without_another_model_call_and_preserves_usage(
    setup_backend, monkeypatch
):
    from benchmarks.evaluation.agent_test_runner import AgentExecutionError, DockerAgentTestRunner
    from benchmarks.evaluation.agent_worker import build_evaluation_coordinator, collect_result

    _, fake, lock, repo, _ = setup_backend
    (repo / "TASK.md").write_text("Repair the owned test.\n", encoding="utf-8")
    fail_calls(fake)
    client = FakeLLM(
        [
            replace(
                model_tool_turn("target", "run_target_test", {}),
                prompt_tokens=9,
                completion_tokens=2,
            )
        ]
    )
    original_complete = client.complete

    def respond_then_break_docker(messages, tools):
        response = original_complete(messages, tools)
        fake.problem = "create"
        return response

    client.complete = respond_then_break_docker
    monkeypatch.setattr("pyrepair.cli.DeepSeekClient", lambda **kwargs: client)
    output = lock.parent / "repair-output"
    runner = DockerAgentTestRunner(lock, public_spec(repo), output / "tests")
    coordinator = build_evaluation_coordinator(
        AppConfig("offline-only-sentinel", "deepseek-flash"),
        output,
        runner=runner,
        record_usage=True,
    )
    with pytest.raises(AgentExecutionError):
        coordinator.run(RepairRequest(repo))
    result = collect_result(output)
    assert len(client.requests) == 1
    assert result["model_calls"] == {"repair": 1, "review": 0}
    assert result["usage"]["repair"] == {"prompt_tokens": 9, "completion_tokens": 2}
    assert result["usage_complete"] is False


@pytest.mark.parametrize("backend", ["host", "docker"])
def test_opensource_worker_cli_stays_closed_before_credentials_or_model(
    setup_backend, monkeypatch, backend
):
    from benchmarks.evaluation.agent_worker import main

    _, fake, lock, repo, _ = setup_backend
    descriptor = lock.parent / "public-task.json"
    write_json(descriptor, public_spec(repo).to_dict())

    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before credential/model setup")

    monkeypatch.setattr("pyrepair.config.load_config", forbidden)
    output = lock.parent / "should-not-exist"
    with pytest.raises(ValueError, match="opensource|backend"):
        main(
            [
                "--repo",
                str(repo),
                "--output",
                str(output),
                "--model",
                "deepseek-flash",
                "--backend",
                backend,
                "--public-task",
                str(descriptor),
                "--environment-lock",
                str(lock),
            ]
        )
    assert not output.exists()
    assert not fake.commands
