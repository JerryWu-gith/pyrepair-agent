import json
from dataclasses import asdict

import pytest

from benchmarks.evaluation.experiment import digest
from benchmarks.evaluation.review_fixtures import PROTOCOL, review_runtime, save_json
from pyrepair.models import ModelTurn
from pyrepair.recorder import RecorderError
from tests.fakes import FakeLLM
from tests.test_review_agent import failure_report, patch_snapshot

APPROVE = '{"approved":true,"risk":"low","findings":[],"reason":"ok"}'
REJECT = '{"approved":false,"risk":"high","findings":["side effect"],"reason":"no"}'


@pytest.fixture
def prepared(tmp_path):
    return make_prepared(tmp_path)


def make_prepared(tmp_path):
    inputs = {
        f"candidate_{n}": {
            "failure": asdict(failure_report()),
            "changes": [asdict(c) for c in patch_snapshot().changes],
            "task_contract": "Return sum. Public description only.",
        }
        for n in range(6)
    }
    payload = {
        "protocol": PROTOCOL,
        "runtime": review_runtime(),
        "inputs": inputs,
        "labels": {key: i % 2 == 0 for i, key in enumerate(inputs)},
        "provenance": {"grading_canary": "PRIVATE_ONLY_CANARY"},
    }
    path = tmp_path / "prepared"
    save_json(path / "prepared.json", {"payload": payload, "digest": digest(payload)})
    return path


def test_schedule_pairs_are_adjacent_balanced_and_independent(prepared, tmp_path):
    from benchmarks.evaluation.review_evaluation import run_review, schedule

    rows = schedule([f"candidate_{n}" for n in range(6)], 3)
    assert len(rows) == 36
    assert [r["arm"] for r in rows[::2]].count("A") == 9
    client = FakeLLM([ModelTurn(APPROVE, "DO_NOT_PERSIST_REASONING", (), 10, 5)] * 36)
    options = []

    def factory(**kwargs):
        options.append(kwargs)
        return client

    out = run_review(
        prepared,
        tmp_path / "run",
        live=True,
        model="deepseek-flash",
        repeats=3,
        request_cap=36,
        client_factory=factory,
    )
    assert options == [{"model": "deepseek-flash", "max_retries": 0}]
    assert len(client.requests) == 36
    for i in range(0, 36, 2):
        left, right = client.requests[i : i + 2]
        assert left[1] == right[1] == []
        assert len(left[0]) == len(right[0]) == 2
        assert left[0][0] == right[0][0]
        a, b = json.loads(left[0][1]["content"]), json.loads(right[0][1]["content"])
        contracts = {a.pop("task_contract")["content"], b.pop("task_contract")["content"]}
        assert contracts == {"", "Return sum. Public description only."}
        assert a == b
    for messages, _ in client.requests:
        assert "PRIVATE_ONLY_CANARY" not in json.dumps(messages)
    assert not any(
        "DO_NOT_PERSIST_REASONING" in p.read_text(encoding="utf-8") for p in out.rglob("*.json")
    )


@pytest.mark.parametrize("live, cap", [(False, 36), (True, 35)])
def test_authority_and_budget_checked_before_client_initialization(prepared, tmp_path, live, cap):
    from benchmarks.evaluation.review_evaluation import run_review

    def forbidden(**kwargs):
        pytest.fail("no client may be initialized")

    with pytest.raises(ValueError):
        run_review(
            prepared,
            tmp_path / "run",
            live=live,
            model="deepseek-flash",
            repeats=3,
            request_cap=cap,
            client_factory=forbidden,
        )
    assert not (tmp_path / "run").exists()


def test_existing_output_and_changed_runtime_refuse_new_requests(prepared, tmp_path, monkeypatch):
    from benchmarks.evaluation import review_fixtures
    from benchmarks.evaluation.review_evaluation import run_review

    def forbidden(**kwargs):
        pytest.fail("no client may be initialized")

    output = tmp_path / "run"
    output.mkdir()
    with pytest.raises(FileExistsError):
        run_review(
            prepared,
            output,
            live=True,
            model="deepseek-flash",
            repeats=1,
            request_cap=12,
            client_factory=forbidden,
        )
    monkeypatch.setattr(review_fixtures, "review_runtime", lambda: {"changed": True})
    with pytest.raises(ValueError, match="identity"):
        run_review(
            prepared,
            tmp_path / "new",
            live=True,
            model="deepseek-flash",
            repeats=1,
            request_cap=12,
            client_factory=forbidden,
        )


@pytest.mark.parametrize("fail_at, expected_calls", [("started.json", 0), ("result.json", 1)])
def test_persistence_failure_stops_next_request(
    prepared, tmp_path, monkeypatch, fail_at, expected_calls
):
    from benchmarks.evaluation import review_evaluation as ev

    real = ev.save_json

    def fail(path, data):
        if path.name == fail_at:
            raise RecorderError("simulated disk failure")
        return real(path, data)

    monkeypatch.setattr(ev, "save_json", fail)
    client = FakeLLM([ModelTurn(APPROVE, None, (), 10, 5)] * 12)
    with pytest.raises(RecorderError):
        ev.run_review(
            prepared,
            tmp_path / "run",
            live=True,
            model="deepseek-flash",
            repeats=1,
            request_cap=12,
            client_factory=lambda **kw: client,
        )
    assert len(client.requests) == expected_calls
    if expected_calls:
        assert len(list((tmp_path / "run").rglob("started.json"))) == 1
        assert not list((tmp_path / "run").rglob("result.json"))


@pytest.mark.parametrize("error_kind", ["api_error", "parse_error"])
@pytest.mark.parametrize("fail_on", [1, 4])
def test_first_error_stops_requests_and_keeps_redacted_evidence(
    prepared, tmp_path, monkeypatch, error_kind, fail_on
):
    from benchmarks.evaluation.review_evaluation import run_review
    from benchmarks.evaluation.review_reporting import write_report

    monkeypatch.setenv("DEEPSEEK_API_KEY", "SECRET_TEST_CANARY")

    class FailingClient:
        count = 0

        def complete(self, messages, tools):
            self.count += 1
            if self.count == fail_on:
                if error_kind == "api_error":
                    raise RuntimeError("network SECRET_TEST_CANARY")
                return ModelTurn("bad JSON SECRET_TEST_CANARY", "REASONING_CANARY", (), 0, 0)
            # A valid rejection is a judgment, not an execution error.
            return ModelTurn(REJECT, "REASONING_CANARY", (), 10, 5)

    client = FailingClient()
    out = run_review(
        prepared,
        tmp_path / "run",
        live=True,
        model="deepseek-flash",
        repeats=1,
        request_cap=12,
        client_factory=lambda **kw: client,
    )
    assert client.count == fail_on
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.rglob("result.json"))]
    assert len(results) == fail_on
    assert results[-1]["status"] == error_kind
    assert results[-1]["usage_known"] is False
    assert all(r["status"] == "valid" for r in results[:-1])
    assert not (out / "requests" / f"{fail_on + 1:04d}").exists()
    saved = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*.json"))
    assert "SECRET_TEST_CANARY" not in saved and "REASONING_CANARY" not in saved
    summary = write_report(out)
    assert summary["planned_requests"] == 12
    assert summary["started_requests"] == fail_on
    assert sum(a["not_started"] for a in summary["arms"].values()) == 12 - fail_on
    assert sum(a[error_kind + "s"] for a in summary["arms"].values()) == 1
    assert sum(a["correct"]["denominator"] for a in summary["arms"].values()) == 12
