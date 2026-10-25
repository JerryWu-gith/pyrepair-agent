"""Dataset metadata is evaluator-only and never changes Review business inputs."""

import json

import pytest

from benchmarks.evaluation.experiment import digest
from benchmarks.evaluation.review_evaluation import run_review
from benchmarks.evaluation.review_fixtures import load_prepared, save_json
from benchmarks.evaluation.review_reporting import load_run, write_report
from pyrepair.models import ModelTurn
from tests.fakes import FakeLLM
from tests.test_review_evaluation import APPROVE, make_prepared


def twelve_prepared(tmp_path):
    path = make_prepared(tmp_path)
    data = load_prepared(path)
    example = next(iter(data["inputs"].values()))
    data["inputs"] = {f"hard_{n}": example for n in range(12)}
    data["labels"] = {key: n % 2 == 0 for n, key in enumerate(data["inputs"])}
    data["dataset"] = {
        "id": "PRIVATE_DATASET_CANARY",
        "source_kind": "synthetic",
        "split": "dev",
        "candidate_cases": {f"hard_{n}": f"task_{n // 2}" for n in range(12)},
    }
    save_json(path / "prepared.json", {"payload": data, "digest": digest(data)})
    return path


def test_twelve_candidates_get_72_isolated_calls_and_dynamic_report(tmp_path):
    path = twelve_prepared(tmp_path)
    client = FakeLLM([ModelTurn(APPROVE, None, (), 10, 5)] * 72)
    out = run_review(
        path,
        tmp_path / "run",
        live=True,
        model="deepseek-flash",
        repeats=3,
        request_cap=72,
        client_factory=lambda **kw: client,
    )
    manifest, _, _ = load_run(out)
    assert manifest["dataset"]["id"] == "PRIVATE_DATASET_CANARY"
    assert len(set(manifest["dataset"]["candidate_cases"].values())) == 6
    assert len(client.requests) == 72
    for i in range(0, 72, 2):
        left, right = client.requests[i : i + 2]
        assert left[1] == right[1] == []
        assert left[0][0] == right[0][0]
        a, b = [json.loads(request[0][1]["content"]) for request in (left, right)]
        assert {a.pop("task_contract")["content"], b.pop("task_contract")["content"]} == {
            "",
            "Return sum. Public description only.",
        }
        assert a == b
    payload = json.dumps(client.requests)
    assert "PRIVATE_DATASET_CANARY" not in payload
    assert "PRIVATE_ONLY_CANARY" not in payload
    summary = write_report(out)
    assert summary["planned_requests"] == 72
    assert summary["arms"]["A"]["correct"] == {"numerator": 18, "denominator": 36}
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "6 题、12 候选" in report
    assert "三题是" not in report and "这六候选" not in report
    assert "synthetic/dev" in report


def test_72_schedule_rejects_71_budget_before_client(tmp_path):
    path = twelve_prepared(tmp_path)

    def forbidden(**kw):
        pytest.fail("budget must be checked before client creation")

    with pytest.raises(ValueError, match="72 planned"):
        run_review(
            path,
            tmp_path / "run",
            live=True,
            model="deepseek-flash",
            repeats=3,
            request_cap=71,
            client_factory=forbidden,
        )
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("bad", ["missing_candidate", "unknown_candidate", "empty_task", "count"])
def test_invalid_dataset_mapping_rejected_before_client(tmp_path, bad):
    path = twelve_prepared(tmp_path)
    document = json.loads((path / "prepared.json").read_text(encoding="utf-8"))
    data = document["payload"]
    mapping = data["dataset"]["candidate_cases"]
    if bad == "missing_candidate":
        mapping.pop("hard_0")
    elif bad == "unknown_candidate":
        mapping["other"] = "task"
    elif bad == "empty_task":
        mapping["hard_0"] = ""
    else:
        data["dataset"]["task_count"] = 999
    save_json(path / "prepared.json", {"payload": data, "digest": digest(data)})

    def forbidden(**kw):
        pytest.fail("invalid metadata must be rejected before client creation")

    with pytest.raises(ValueError, match="dataset"):
        run_review(
            path,
            tmp_path / "run",
            live=True,
            model="deepseek-flash",
            repeats=3,
            request_cap=72,
            client_factory=forbidden,
        )


def test_fixture_metadata_derives_mapping_and_rejects_false_scope():
    from benchmarks.evaluation.review_assets import dataset_metadata

    fixture = {
        "dataset": {"id": "review-hard-v1", "source_kind": "synthetic", "split": "dev"},
        "candidates": [{"id": "a", "case_id": "one"}, {"id": "b", "case_id": "one"}],
    }
    assert dataset_metadata(fixture) == {
        "id": "review-hard-v1",
        "source_kind": "synthetic",
        "split": "dev",
        "candidate_cases": {"a": "one", "b": "one"},
    }
    fixture["dataset"]["split"] = "holdout"
    with pytest.raises(ValueError, match="dataset"):
        dataset_metadata(fixture)
