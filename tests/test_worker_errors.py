import errno
import json
from types import SimpleNamespace

import pytest

from benchmarks.evaluation import agent_worker
from pyrepair.recorder import RecorderError


def test_worker_persists_redacted_cause_and_os_codes(tmp_path, monkeypatch, capsys):
    secret = "offline-secret-canary-never-log"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    output = tmp_path / "agent"

    def fail(request):
        cause = PermissionError(errno.EACCES, "locked path " + secret)
        cause.winerror = 5
        try:
            raise cause
        except PermissionError as exc:
            raise RecorderError("cannot replace " + secret) from exc

    coordinator = SimpleNamespace(context_builder=object(), run=fail)
    monkeypatch.setattr("pyrepair.cli.build_coordinator", lambda *args, **kwargs: coordinator)

    code = agent_worker.main(
        ["--repo", str(tmp_path / "repo"), "--output", str(output), "--model", "deepseek-flash"]
    )

    assert code == 2
    details = json.loads((output / "worker-error.json").read_text(encoding="utf-8"))
    chain = details["exception_chain"]
    assert [item["type"] for item in chain] == ["RecorderError", "PermissionError"]
    assert chain[1]["errno"] == errno.EACCES
    assert chain[1]["winerror"] == 5
    result = json.loads((output / "agent-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "error"
    assert result["usage_complete"] is False
    assert result["error_details"] == details
    # The parent collector and interrupted-run recovery must retain diagnostics too.
    assert agent_worker.collect_result(output)["error_details"] == details
    combined = capsys.readouterr().out + "".join(p.read_text() for p in output.iterdir())
    assert secret not in combined
    assert "[REDACTED]" in combined


def test_error_details_cap_message_size_and_stop_cause_cycles():
    secret = "offline-secret-canary"
    error = RuntimeError(secret + "x" * 3000)
    error.__cause__ = error

    details = agent_worker.exception_details(error, (secret,))

    assert len(details["exception_chain"]) == 1
    assert len(details["exception_chain"][0]["message"]) <= 2000
    assert secret not in json.dumps(details)
    assert "[REDACTED]" in details["exception_chain"][0]["message"]


@pytest.mark.parametrize("contents", ["not-json", "[]", '{}', '{"exception_chain": []}'])
def test_corrupt_worker_diagnostics_remain_an_error(tmp_path, contents):
    (tmp_path / "worker-error.json").write_text(contents, encoding="utf-8")

    result = agent_worker.collect_result(tmp_path)

    assert result["status"] == "error"
    assert result["usage_complete"] is False
    assert result["error"] == "invalid_worker_error_details"


def test_diagnostic_write_failure_does_not_replace_original_error(tmp_path, monkeypatch, capsys):
    secret = "offline-secret-canary"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    def fail(request):
        raise RecorderError("original " + secret)

    coordinator = SimpleNamespace(context_builder=object(), run=fail)
    monkeypatch.setattr("pyrepair.cli.build_coordinator", lambda *args, **kwargs: coordinator)
    original_write = agent_worker.write_json

    def write_except_diagnostic(path, value):
        if path.name == "worker-error.json":
            raise PermissionError(errno.EACCES, "secondary " + secret)
        original_write(path, value)

    monkeypatch.setattr(agent_worker, "write_json", write_except_diagnostic)
    code = agent_worker.main(
        ["--repo", str(tmp_path / "repo"), "--output", str(tmp_path), "--model", "deepseek-flash"]
    )

    assert code == 2
    result = json.loads((tmp_path / "agent-result.json").read_text(encoding="utf-8"))
    assert result["error_details"]["exception_chain"][0]["type"] == "RecorderError"
    assert result["error_details"]["exception_chain"][0]["message"] == "original [REDACTED]"
    assert secret not in capsys.readouterr().out + json.dumps(result)
    # run_agent collects again, then the experiment overwrites agent-result.json.
    # That round trip must not discard the child's fallback diagnostics.
    collected = agent_worker.collect_result(tmp_path)
    assert collected["error_details"] == result["error_details"]
    original_write(tmp_path / "agent-result.json", collected)
    assert agent_worker.collect_result(tmp_path)["error_details"] == result["error_details"]


def test_saved_summary_alone_cannot_claim_success_or_usage(tmp_path):
    agent_worker.write_json(
        tmp_path / "agent-result.json",
        {"status": "success", "usage_complete": True, "model_calls": {"repair": 999}},
    )

    result = agent_worker.collect_result(tmp_path)

    assert result["status"] == "error"
    assert result["usage_complete"] is False
    assert result["model_calls"] == {"repair": 0, "review": 0}


def test_exception_details_honor_suppressed_context_and_bound_depth():
    suppressed = RuntimeError("public error")
    suppressed.__context__ = ValueError("suppressed")
    suppressed.__suppress_context__ = True
    assert len(agent_worker.exception_details(suppressed)["exception_chain"]) == 1

    error = RuntimeError("root")
    current = error
    for index in range(10):
        current.__cause__ = RuntimeError(str(index))
        current = current.__cause__
    assert len(agent_worker.exception_details(error)["exception_chain"]) == 5
