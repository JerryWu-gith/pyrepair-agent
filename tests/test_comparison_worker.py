"""The new worker validates public capabilities before constructing any client."""

import json

import pytest

from benchmarks.evaluation.comparison_budget import read_usage
from benchmarks.evaluation.live_plan import public_job
from pyrepair.models import ModelTurn
from tests.fakes import FakeLLM
from tests.test_comparison_methods import PATCH
from tests.test_comparison_pack import make_prepared


def owned_job(tmp_path, monkeypatch):
    _, _, path, _ = make_prepared(tmp_path, monkeypatch)
    pack = json.loads((path / "pack.json").read_text("utf-8"))
    return public_job(
        path, pack, pack["identity"]["slots"][0], tmp_path / "o/s0000", tmp_path / "o/q", 37
    )


def test_worker_publishes_candidate_and_durable_response_without_secrets(tmp_path, monkeypatch):
    from benchmarks.evaluation.comparison_worker import run_job

    job = owned_job(tmp_path, monkeypatch)
    fake = FakeLLM([ModelTurn(PATCH, None, (), 8, 3, "stop")])
    result = run_job(job, lambda config: fake)
    assert result["status"] == "candidate"
    assert "+    return a + b" in result["patch"]
    assert read_usage(tmp_path / "o/q")["reserved_calls"] == 1
    assert (tmp_path / "o/s0000/responses/response-000001.json").is_file()
    assert len(fake.requests) == 1
    assert "hidden_tests" not in str(fake.requests)


@pytest.mark.parametrize("failure", ["spec", "repo", "config", "environment", "private"])
def test_invalid_job_is_rejected_without_constructing_client(tmp_path, monkeypatch, failure):
    from benchmarks.evaluation.comparison_worker import run_job

    job = owned_job(tmp_path, monkeypatch)
    if failure == "spec":
        job["spec"]["case_id"] = "different"
    elif failure == "repo":
        from pathlib import Path

        Path(job["repo"]).joinpath("src/app.py").write_text("changed", encoding="utf-8")
    elif failure == "config":
        job["config"]["endpoint"] = "https://another.invalid"
    elif failure == "environment":
        job["environment"]["image_id"] = "changed"
    else:
        job["hidden_tests"] = ["do-not-expose"]

    def forbidden(config):
        pytest.fail("invalid input reached provider construction")

    with pytest.raises((ValueError, KeyError)):
        run_job(job, forbidden)
    assert not (tmp_path / "o").exists()


def test_api_error_is_reserved_once_without_candidate_or_retry(tmp_path, monkeypatch):
    from benchmarks.evaluation.comparison_worker import run_job

    job = owned_job(tmp_path, monkeypatch)

    class FailingClient:
        def complete(self, messages, tools):
            raise RuntimeError("owned upstream error")

    with pytest.raises(RuntimeError):
        run_job(job, lambda config: FailingClient())
    usage = read_usage(tmp_path / "o/q")
    assert usage["reserved_calls"] == 1
    assert usage["responses"] == 0
    assert usage["roles"]["single-shot"]["prompt_tokens"] is None
    assert not (tmp_path / "o/s0000/candidate.json").exists()


def test_worker_refuses_existing_candidate_before_provider_construction(tmp_path, monkeypatch):
    from benchmarks.evaluation.comparison_budget import write_new
    from benchmarks.evaluation.comparison_worker import run_job

    job = owned_job(tmp_path, monkeypatch)
    write_new(tmp_path / "o/s0000/candidate.json", {"old": True})

    def forbidden(config):
        pytest.fail("worker must not request again to overwrite a candidate")

    with pytest.raises(FileExistsError):
        run_job(job, forbidden)


def test_direct_worker_entry_needs_parent_capability_before_credential_lookup(
    tmp_path, monkeypatch
):
    from benchmarks.evaluation.comparison_budget import write_new
    from benchmarks.evaluation.comparison_worker import main

    job = owned_job(tmp_path, monkeypatch)
    path = tmp_path / "job.json"
    write_new(path, job)
    monkeypatch.delenv("PYREPAIR_APPROVED_JOB_HASH", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "owned-sentinel-not-a-real-key")
    assert main(["--job", str(path), "--execute-authorized"]) == 2
    assert not (tmp_path / "o").exists()
