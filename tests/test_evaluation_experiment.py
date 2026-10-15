import json

import pytest

from benchmarks.evaluation.cases import load_cases
from tests.evaluation_helpers import make_case


@pytest.fixture
def case(tmp_path):
    return load_cases(make_case(tmp_path / "bank"))[0]


def scripted_agent(case, output, model):
    assert model == "deepseek-v4-flash"
    output.mkdir(parents=True, exist_ok=True)
    (output / "fix.patch").write_bytes(case.gold_patch.read_bytes())
    return {
        "status": "success",
        "attempts": 1,
        "patch_path": "fix.patch",
        "usage": {
            "repair": {"prompt_tokens": 10, "completion_tokens": 5},
            "review": {"prompt_tokens": 3, "completion_tokens": 2},
        },
        "usage_complete": True,
    }


def test_repeated_trials_and_terminal_failures_are_never_overwritten(case, tmp_path):
    from benchmarks.evaluation.experiment import create_experiment, run_experiment

    path = create_experiment([case], tmp_path / "exp", "deepseek-v4-flash", 3)
    count = 0

    def executor(case, output, model):
        nonlocal count
        count += 1
        result = scripted_agent(case, output, model)
        if count == 2:
            (output / "fix.patch").write_bytes(case.wrong_patch.read_bytes())
        if count == 3:
            result.update(status="error", usage_complete=False)
        return result

    records = run_experiment(path, [case], agent_executor=executor)
    assert [r["trial_index"] for r in records] == [1, 2, 3]
    assert [r["passed"] for r in records] == [True, False, False]
    assert records[1]["grade"]["status"] == "hidden_failed"
    assert records[2]["agent"]["status"] == "error"
    before = (path / "trials.jsonl").read_bytes()

    def forbidden(*args):
        pytest.fail("finished trials must not spend more model calls")

    assert run_experiment(path, [case], agent_executor=forbidden) == records
    assert (path / "trials.jsonl").read_bytes() == before


def test_resume_rejects_changed_assets_or_config(case, tmp_path):
    from benchmarks.evaluation.experiment import create_experiment, run_experiment

    path = create_experiment([case], tmp_path / "exp", "deepseek-v4-flash", 1)
    case.description.write_text("changed contract")
    with pytest.raises(ValueError, match="identity|fingerprint"):
        run_experiment(path, [case], agent_executor=scripted_agent)


def test_grader_interruption_reuses_completed_agent(case, tmp_path, monkeypatch):
    from benchmarks.evaluation import experiment

    path = experiment.create_experiment([case], tmp_path / "exp", "deepseek-v4-flash", 1)
    real = experiment.grade_patch

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(experiment, "grade_patch", interrupt)
    with pytest.raises(KeyboardInterrupt):
        experiment.run_experiment(path, [case], agent_executor=scripted_agent)
    monkeypatch.setattr(experiment, "grade_patch", real)

    def forbidden(*args):
        pytest.fail("grading resume must not invoke the Agent again")

    results = experiment.run_experiment(path, [case], agent_executor=forbidden)
    assert results[0]["passed"] is True
    assert results[0]["execution_index"] == 1


def test_interrupted_agent_gets_new_execution_and_preserves_history(case, tmp_path):
    from benchmarks.evaluation.experiment import create_experiment, load_events, run_experiment

    path = create_experiment([case], tmp_path / "exp", "deepseek-v4-flash", 1)

    def interrupt(case, output, model):
        (output / "partial.log").write_text("spent a model call before interrupt")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_experiment(path, [case], agent_executor=interrupt)
    results = run_experiment(path, [case], agent_executor=scripted_agent)
    assert results[0]["execution_index"] == 2
    assert results[0]["interrupted_executions"] == 1
    assert results[0]["cost_complete"] is False
    assert list(path.rglob("partial.log"))
    assert len([e for e in load_events(path) if e["event"] == "started"]) == 2


def test_invalid_journal_and_concurrent_writer_fail_closed(case, tmp_path):
    from benchmarks.evaluation.experiment import create_experiment, load_events, run_experiment

    path = create_experiment([case], tmp_path / "exp", "deepseek-v4-flash", 1)
    (path / "writer.lock").write_text("another writer")
    with pytest.raises(ValueError, match="lock"):
        run_experiment(path, [case], agent_executor=scripted_agent)
    (path / "writer.lock").unlink()
    (path / "trials.jsonl").write_text('{"case_id":"old-v1","status":"success"}\n')
    with pytest.raises(ValueError):
        load_events(path)
    (path / "trials.jsonl").write_text("{")
    with pytest.raises(ValueError):
        load_events(path)


def test_worker_usage_separates_roles_and_incomplete_trace(tmp_path):
    from benchmarks.evaluation.agent_worker import collect_result

    root = tmp_path / ".pyrepair/runs/evaluation"
    root.mkdir(parents=True)
    (root / "report.json").write_text(
        json.dumps(
            {
                "status": "success",
                "attempt_count": 1,
                "attempts": [{"attempt": 1, "tool_calls_used": 4, "outcome": "success"}],
            }
        )
    )
    (root / "fix.patch").write_text("a patch")
    events = [
        {"type": "model_turn", "role": "repair", "prompt_tokens": 12, "completion_tokens": 4},
        {"type": "model_turn", "role": "review", "prompt_tokens": 6, "completion_tokens": 2},
        {"type": "run_finished", "status": "success"},
    ]
    (root / "trace.jsonl").write_text("\n".join(map(json.dumps, events)) + "\n")
    result = collect_result(tmp_path)
    assert result["usage"]["repair"]["prompt_tokens"] == 12
    assert result["usage"]["review"]["completion_tokens"] == 2
    assert result["usage_complete"] is True
    assert result["attempts"] == 1
    assert result["tool_calls"] == 4
    assert result["model_calls"] == {"repair": 1, "review": 1}
    (root / "report.json").write_text("{}")
    result = collect_result(tmp_path)
    assert result["status"] == "error"
    assert result["usage_complete"] is False


def test_public_contract_reaches_model_context_without_private_assets(case, tmp_path):
    from benchmarks.evaluation.agent_worker import PublicContractContext
    from benchmarks.evaluation.cases import prepare_case
    from pyrepair.context_builder import ContextBuilder
    from pyrepair.models import FailureReport

    repo = prepare_case(case, tmp_path / "repo")
    bundle = PublicContractContext(ContextBuilder()).build(
        repo, FailureReport("tests/test_app.py::test_add", "AssertionError", "", "assert -1 == 5")
    )
    text = bundle.repo_overview + "\n".join(s.content for s in bundle.snippets)
    assert "Return the sum of two integers" in text
    assert "gold.patch" not in text
    assert bundle.total_chars <= 16000


def test_missing_candidate_artifact_is_terminal_grader_error(case, tmp_path):
    from benchmarks.evaluation.experiment import create_experiment, run_experiment

    path = create_experiment([case], tmp_path / "exp", "deepseek-v4-flash", 1)

    def missing(case, output, model):
        result = scripted_agent(case, output, model)
        (output / "fix.patch").unlink()
        return result

    results = run_experiment(path, [case], agent_executor=missing)
    assert results[0]["passed"] is False
    assert results[0]["grade"]["status"] == "grader_error"
    assert len(run_experiment(path, [case], agent_executor=missing)) == 1


def test_source_identity_covers_internal_pytest_plugin(tmp_path, monkeypatch):
    from benchmarks.evaluation import experiment

    root = tmp_path / "source"
    (root / "src/_pyrepair_agent_internal").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    plugin = root / "src/_pyrepair_agent_internal/pytest_plugin.py"
    plugin.write_text("one")
    monkeypatch.setattr(experiment, "ROOT", root)
    first = experiment.runtime_identity()["source_hash"]
    plugin.write_text("two")
    assert experiment.runtime_identity()["source_hash"] != first


def write_raw_result(output, patch_text):
    root = output / ".pyrepair/runs/evaluation"
    root.mkdir(parents=True)
    (root / "report.json").write_text(
        json.dumps({"status": "success", "attempt_count": 1, "attempts": [{"tool_calls_used": 3}]})
    )
    (root / "fix.patch").write_text(patch_text)
    events = [
        {"type": "model_turn", "role": "repair", "prompt_tokens": 0, "completion_tokens": 0},
        {"type": "run_finished", "status": "success", "attempt_count": 1},
    ]
    (root / "trace.jsonl").write_text("\n".join(map(json.dumps, events)) + "\n")


def test_zero_usage_trace_is_unknown_not_zero_cost(tmp_path):
    from benchmarks.evaluation.agent_worker import collect_result

    write_raw_result(tmp_path, "patch")
    result = collect_result(tmp_path)
    assert result["status"] == "success"
    assert result["usage_complete"] is False


def test_resume_recovers_raw_finished_report_before_summary_write(case, tmp_path):
    from benchmarks.evaluation.experiment import create_experiment, run_experiment

    path = create_experiment([case], tmp_path / "exp", "deepseek-v4-flash", 1)

    def interrupt(case, output, model):
        write_raw_result(output, case.gold_patch.read_text())
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_experiment(path, [case], agent_executor=interrupt)

    def forbidden(*args):
        pytest.fail("complete raw evidence must avoid a second paid Agent run")

    results = run_experiment(path, [case], agent_executor=forbidden)
    assert results[0]["passed"] is True
    assert results[0]["execution_index"] == 1
    assert results[0]["cost_complete"] is False


def test_raw_deepseek_error_remains_error_with_unknown_cost(tmp_path):
    from benchmarks.evaluation.agent_worker import collect_result

    write_raw_result(tmp_path, "")
    root = tmp_path / ".pyrepair/runs/evaluation"
    (root / "report.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "attempt_count": 0,
                "failure_reason": "deepseek_error",
                "attempts": [],
            }
        )
    )
    (root / "trace.jsonl").write_text(
        json.dumps(
            {
                "type": "run_finished",
                "status": "failed",
                "failure_reason": "deepseek_error",
                "attempt_count": 0,
            }
        )
        + "\n"
    )
    result = collect_result(tmp_path)
    assert result["completed_evidence"] is True
    assert result["status"] == "error"
    assert result["usage_complete"] is False


def test_real_worker_assembly_and_independent_grader_with_fake_client(case, tmp_path, monkeypatch):
    import pyrepair.cli
    from benchmarks.evaluation.agent_worker import collect_result, main
    from benchmarks.evaluation.cases import prepare_case
    from benchmarks.evaluation.grading import grade_patch
    from tests.fakes import FakeLLM, model_text_turn, model_tool_turn

    turns = [
        model_tool_turn(
            "replace",
            "replace_text",
            {"path": "src/app.py", "old_text": "return a - b", "new_text": "return a + b"},
        ),
        model_tool_turn("diff", "show_diff", {}),
        model_tool_turn("test", "run_target_test", {}),
        model_text_turn("completed"),
        model_text_turn(
            json.dumps(
                {"approved": True, "risk": "low", "findings": [], "reason": "addition restored"}
            )
        ),
    ]
    client = FakeLLM(turns)
    monkeypatch.setattr(pyrepair.cli, "DeepSeekClient", lambda **kwargs: client)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-secret")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--rootdir=.")
    repo = prepare_case(case, tmp_path / "input")
    output = tmp_path / "agent"
    assert main(["--repo", str(repo), "--output", str(output), "--model", "deepseek-v4-flash"]) == 0
    result = collect_result(output)
    assert result["status"] == "success"
    assert result["attempts"] == 1
    assert result["tool_calls"] == 3
    assert result["model_calls"] == {"repair": 4, "review": 1}
    assert "a - b" in (repo / "src/app.py").read_text()
    patch_text = (output / result["patch_path"]).read_text()
    assert grade_patch(case, patch_text, tmp_path / "grade")["status"] == "passed"
