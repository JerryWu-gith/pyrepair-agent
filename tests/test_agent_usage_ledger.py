"""A tool crash must not erase the model response that paid for that tool call."""

import json

import pytest

from pyrepair.models import ModelTurn
from tests.fakes import FakeLLM


def test_response_ledger_preserves_usage_without_finished_agent_trace(tmp_path):
    from benchmarks.evaluation.agent_usage import RecordingModelClient, ResponseLedger
    from benchmarks.evaluation.agent_worker import collect_result

    ledger = ResponseLedger(tmp_path / "model-usage.jsonl")
    client = RecordingModelClient(FakeLLM([ModelTurn("done", None, (), 11, 3)]), "repair", ledger)
    assert client.complete([], []).content == "done"

    result = collect_result(tmp_path)

    assert result["model_calls"] == {"repair": 1, "review": 0}
    assert result["usage"]["repair"] == {"prompt_tokens": 11, "completion_tokens": 3}
    assert result["usage_complete"] is False  # No completed repair evidence.
    assert result["usage_source"] == "response_ledger"


def test_response_ledger_does_not_double_count_coordinator_turns(tmp_path):
    from benchmarks.evaluation.agent_usage import RecordingModelClient, ResponseLedger
    from benchmarks.evaluation.agent_worker import collect_result

    ledger = ResponseLedger(tmp_path / "model-usage.jsonl")
    RecordingModelClient(FakeLLM([ModelTurn("done", None, (), 11, 3)]), "repair", ledger).complete(
        [], []
    )
    root = tmp_path / ".pyrepair/runs/evaluation"
    root.mkdir(parents=True)
    (root / "report.json").write_text(
        json.dumps({"status": "failed", "attempt_count": 1, "attempts": []})
    )
    (root / "trace.jsonl").write_text(
        "\n".join(
            map(
                json.dumps,
                [
                    {
                        "type": "model_turn",
                        "role": "repair",
                        "prompt_tokens": 11,
                        "completion_tokens": 3,
                    },
                    {"type": "run_finished", "status": "failed"},
                ],
            )
        )
    )
    result = collect_result(tmp_path)
    assert result["model_calls"]["repair"] == 1
    assert result["usage"]["repair"]["prompt_tokens"] == 11
    assert result["usage_complete"] is True


def test_failed_model_call_keeps_known_previous_usage_and_marks_unknown(tmp_path):
    from benchmarks.evaluation.agent_usage import RecordingModelClient, ResponseLedger
    from benchmarks.evaluation.agent_worker import collect_result

    ledger = ResponseLedger(tmp_path / "model-usage.jsonl")
    client = RecordingModelClient(FakeLLM([ModelTurn("done", None, (), 11, 3)]), "repair", ledger)
    client.complete([], [])
    with pytest.raises(AssertionError):
        client.complete([], [])
    result = collect_result(tmp_path)
    assert result["model_calls"]["repair"] == 2
    assert result["usage"]["repair"] == {"prompt_tokens": 11, "completion_tokens": 3}
    assert result["usage_complete"] is False
    assert result["transport_requests"] is None


def test_response_ledger_never_serializes_messages_or_reasoning(tmp_path):
    from benchmarks.evaluation.agent_usage import RecordingModelClient, ResponseLedger

    ledger = ResponseLedger(tmp_path / "model-usage.jsonl")
    client = RecordingModelClient(
        FakeLLM([ModelTurn("sensitive-content", "sensitive-reasoning", (), 2, 1)]), "review", ledger
    )
    client.complete([{"role": "user", "content": "sensitive-request"}], [])
    text = (tmp_path / "model-usage.jsonl").read_text("utf-8")
    assert "sensitive" not in text


def test_response_ledger_refuses_to_append_to_old_experiment(tmp_path):
    from benchmarks.evaluation.agent_usage import ResponseLedger

    path = tmp_path / "model-usage.jsonl"
    path.write_text("old\n")
    with pytest.raises(FileExistsError):
        ResponseLedger(path)
    assert path.read_text() == "old\n"


def test_empty_ledger_cannot_erase_completed_trace_usage(tmp_path):
    from benchmarks.evaluation.agent_usage import ResponseLedger
    from benchmarks.evaluation.agent_worker import collect_result

    ResponseLedger(tmp_path / "model-usage.jsonl")
    root = tmp_path / ".pyrepair/runs/evaluation"
    root.mkdir(parents=True)
    (root / "report.json").write_text(
        json.dumps({"status": "success", "attempt_count": 1, "attempts": []})
    )
    (root / "trace.jsonl").write_text(
        "\n".join(
            map(
                json.dumps,
                [
                    {
                        "type": "model_turn",
                        "role": "repair",
                        "prompt_tokens": 11,
                        "completion_tokens": 3,
                    },
                    {"type": "run_finished", "status": "success"},
                ],
            )
        )
    )
    result = collect_result(tmp_path)
    assert result["status"] == "error"
    assert result["usage_complete"] is False
    assert result["usage"]["repair"]["prompt_tokens"] == 11
