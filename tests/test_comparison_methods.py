import json

import pytest

from benchmarks.evaluation.agent_input import prepare_agent_input
from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.comparison_budget import CallBudget, GuardedClient, read_usage
from benchmarks.evaluation.comparison_evidence import capture_evidence, initial_facts
from pyrepair.models import ModelTurn, ToolCallRequest
from tests.evaluation_helpers import make_case
from tests.test_comparison_evidence import OwnedRunner

PATCH = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"


@pytest.mark.parametrize(
    "text", [PATCH, "```diff\n" + PATCH + "```", "\n```patch\n" + PATCH + "```\n"]
)
def test_single_shot_accepts_only_fixed_diff_formats(text):
    from benchmarks.evaluation.comparison_methods import extract_patch

    assert extract_patch(ModelTurn(text, None, (), stop_reason="stop")) == PATCH


@pytest.mark.parametrize(
    "text,calls,stop",
    [
        ("Here is the patch:\n" + PATCH, (), "stop"),
        ("```diff\n" + PATCH + "```\n```diff\n" + PATCH + "```", (), "stop"),
        ("", (), "stop"),
        (PATCH, (), "length"),
        (PATCH, (ToolCallRequest("1", "replace_text", {}),), "tool_calls"),
        ("--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n", (), "stop"),
    ],
)
def test_invalid_response_is_not_repaired_or_interpreted_as_commands(text, calls, stop):
    from benchmarks.evaluation.comparison_methods import extract_patch

    with pytest.raises(ValueError):
        extract_patch(ModelTurn(text, None, calls, stop_reason=stop))


@pytest.mark.parametrize(
    "text,expected", [(PATCH, "candidate"), ("sorry, no patch", "format_error")]
)
def test_single_response_uses_frozen_facts_and_persists_candidate(tmp_path, text, expected):
    from benchmarks.evaluation.comparison_methods import single_shot

    case = load_cases(make_case(tmp_path / "assets"))[0]
    repo = tmp_path / "repo"
    spec = prepare_agent_input(case, repo)
    evidence = capture_evidence(repo, spec, OwnedRunner())

    class Client:
        def complete(self, messages, tools):
            assert tools == []
            payload = json.loads(messages[1]["content"])
            assert payload == initial_facts(evidence, spec)
            assert payload["failure"]["summary"] == "assert -1 == 5"
            assert "hidden_tests" not in str(messages)
            return ModelTurn(text, None, (), 9, 3, "stop")

    output = tmp_path / "result"
    client = GuardedClient(
        Client(),
        CallBudget(tmp_path / "budget", 1),
        "demo--1--single-shot",
        "single-shot",
        1,
        output / "responses",
    )
    result = single_shot(evidence, spec, client, output)
    assert result["status"] == expected
    assert result["patch"] == (PATCH if expected == "candidate" else "")
    assert json.loads((output / "candidate.json").read_text("utf-8")) == result
    assert read_usage(tmp_path / "budget")["reserved_calls"] == 1
    assert len(list((output / "responses").glob("*.json"))) == 1


def test_raw_unguarded_client_is_rejected_before_call():
    from benchmarks.evaluation.comparison_methods import single_shot

    with pytest.raises(ValueError, match="guarded"):
        single_shot({}, None, object(), None)


def test_full_agent_uses_identical_frozen_facts_with_real_owned_tests(tmp_path, monkeypatch):
    from dataclasses import replace

    from benchmarks.evaluation.agent_worker import build_evaluation_coordinator
    from benchmarks.evaluation.comparison_methods import full_agent
    from pyrepair.config import AppConfig
    from pyrepair.testing import TestRunner
    from tests.test_agent_worker_docker import successful_client

    case = load_cases(make_case(tmp_path / "assets"))[0]
    repo = tmp_path / "repo"
    spec = prepare_agent_input(case, repo)
    runner = TestRunner()
    evidence = capture_evidence(repo, spec, runner)
    client = successful_client()
    call = client.turns[0].tool_calls[0]
    client.turns[0] = replace(
        client.turns[0],
        tool_calls=(replace(call, arguments={**call.arguments, "path": "src/app.py"}),),
    )
    monkeypatch.setattr("pyrepair.cli.DeepSeekClient", lambda **kwargs: client)
    output = tmp_path / "agent"
    coordinator = build_evaluation_coordinator(
        AppConfig("owned-no-key", "deepseek-flash"), output, runner=runner
    )
    result = full_agent(
        repo,
        spec,
        evidence,
        coordinator,
        CallBudget(tmp_path / "budget", 36),
        output,
        "demo--1--full-agent",
    )
    assert result["internal_success"] is True
    assert "+    return a + b" in result["patch"]
    assert (repo / "src/app.py").read_text("utf-8").endswith("return a - b\n")
    assert json.loads(client.requests[0][0][1]["content"]) == initial_facts(evidence, spec)
    from benchmarks.evaluation.comparison_methods import single_shot
    from tests.fakes import FakeLLM, model_text_turn
    from tests.test_public_edit_scope import scope_paths

    repair_facts = json.loads(client.requests[0][0][1]["content"])
    assert scope_paths(repair_facts["context"]["repo_overview"]) == ["src/app.py"]
    review = json.loads(client.requests[-1][0][1]["content"])
    assert scope_paths(review["task_contract"]["content"]) == ["src/app.py"]
    assert review["task_contract"]["content"] == evidence["context"]["task_contract"]
    assert review["task_contract"]["trusted"] is False
    baseline_client = FakeLLM([model_text_turn(PATCH)])
    baseline_output = tmp_path / "baseline"
    single_shot(
        evidence,
        spec,
        GuardedClient(
            baseline_client,
            CallBudget(tmp_path / "baseline-budget", 1),
            "demo--1--single-shot",
            "single-shot",
            1,
            baseline_output / "responses",
        ),
        baseline_output,
    )
    assert baseline_client.requests[0][0][1] == client.requests[0][0][1]
    usage = read_usage(tmp_path / "budget")
    assert usage["reserved_calls"] == 5
    assert usage["roles"]["repair"]["prompt_tokens"] == 28
    assert usage["roles"]["review"]["completion_tokens"] == 3
