"""Explicit actual Docker/FakeLLM integration; no provider and no host pytest fallback."""

import json
from dataclasses import replace

import pytest

from benchmarks.evaluation.agent_input import PublicTaskSpec
from benchmarks.evaluation.agent_worker import build_evaluation_coordinator
from benchmarks.evaluation.comparison_budget import CallBudget, GuardedClient, read_usage
from benchmarks.evaluation.comparison_methods import full_agent, single_shot
from benchmarks.evaluation.comparison_pack import prepare_pack, verify_pack
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.docker_runner import DockerTestRunner
from benchmarks.evaluation.layered_grading import grade_layered
from pyrepair.config import AppConfig
from pyrepair.models import ModelTurn
from tests.fakes import FakeLLM
from tests.test_agent_docker_integration import configured_lock
from tests.test_agent_worker_docker import successful_client
from tests.test_comparison_methods import PATCH
from tests.test_layered_grading import owned_case

pytestmark = pytest.mark.docker


def test_real_docker_frozen_pack_both_methods_and_independent_acceptance(tmp_path, monkeypatch):
    from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner

    def forbidden(*args, **kwargs):
        pytest.fail("host test execution is forbidden")

    monkeypatch.setattr("pyrepair.testing.TestRunner.run", forbidden)
    cases = [owned_case(tmp_path)]
    lock = configured_lock()
    pack = prepare_pack(cases, tmp_path / "pack", lock, "deepseek-flash", 3)
    assert len(verify_pack(pack, cases)["identity"]["slots"]) == 6
    public = pack / "p/c00"
    spec = PublicTaskSpec.from_dict(read_json(public / "spec.json"))
    evidence = read_json(public / "evidence.json")
    original = (public / "r/src/app.py").read_bytes()
    budget = CallBudget(tmp_path / "quota", 37)
    single_output = tmp_path / "s"
    client = GuardedClient(
        FakeLLM([ModelTurn(PATCH, None, (), 9, 3, "stop")]),
        budget,
        "demo--1--single-shot",
        "single-shot",
        1,
        single_output / "responses",
    )
    first = single_shot(evidence, spec, client, single_output)
    raw = successful_client()
    call = raw.turns[0].tool_calls[0]
    raw.turns[0] = replace(
        raw.turns[0],
        tool_calls=(replace(call, arguments={**call.arguments, "path": "src/app.py"}),),
    )
    monkeypatch.setattr("pyrepair.cli.DeepSeekClient", lambda **kwargs: raw)
    agent_output = tmp_path / "f"
    runner = DockerAgentTestRunner(lock, spec, agent_output / "t")
    coordinator = build_evaluation_coordinator(
        AppConfig("owned-no-key", "deepseek-flash"), agent_output, runner=runner
    )
    second = full_agent(
        public / "r", spec, evidence, coordinator, budget, agent_output, "demo--1--full-agent"
    )
    for index, result in enumerate((first, second)):
        grade = grade_layered(
            cases[0], result["patch"], tmp_path / f"g{index}", test_runner=DockerTestRunner(lock)
        )
        assert grade["status"] == "core_passed"
        assert grade["extended"]["status"] == "passed"
        assert grade["fully_verified"] is True
    assert second["internal_success"] is True
    assert (
        json.loads(raw.requests[0][0][1]["content"])["failure"]["summary"]
        == evidence["failure"]["summary"]
    )
    assert read_usage(tmp_path / "quota")["reserved_calls"] == 6
    assert (public / "r/src/app.py").read_bytes() == original
    assert "hidden_tests" not in str(raw.requests)
