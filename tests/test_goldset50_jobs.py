"""The fifty-task worker capability is explicit, bounded and public-only."""

import copy
import importlib
import importlib.util
import json
from dataclasses import replace

import pytest

from tests.test_comparison_pack import make_prepared


def api():
    name = "benchmarks.evaluation.goldset_jobs"
    assert importlib.util.find_spec(name) is not None, "fifty-task job authority missing"
    return importlib.import_module(name)


@pytest.fixture
def public_fixture(tmp_path, monkeypatch):
    def selected(pack, cases, lock):
        cases[:] = [replace(cases[0], id="case_01")]

    _, _, path, _ = make_prepared(tmp_path, monkeypatch, selected)
    pack = json.loads((path / "pack.json").read_text("utf-8"))
    return path, pack, tmp_path / "output"


def test_v2_public_job_preserves_real_shared_budget_and_legacy_dispatch(public_fixture):
    from benchmarks.evaluation.live_plan import validate_job

    path, pack, output = public_fixture
    job = api().public_job(
        path, pack, pack["identity"]["slots"][0], output / "s0000", output / "q", 5550
    )
    assert job["version"] == 2
    assert job["profile"] == "goldset50-r1"
    assert job["call_limit"] == 5550
    assert validate_job(job) == job
    assert set(job) == {
        "version",
        "profile",
        "repo",
        "spec",
        "evidence",
        "slot",
        "output",
        "quota",
        "call_limit",
        "environment",
        "config",
    }
    assert not output.exists()
    assert all(s not in json.dumps(job) for s in ("fingerprint", "api_key", "hidden_tests"))


@pytest.mark.parametrize("limit", [1, 2220, 2221, 5550])
def test_v2_accepts_only_explicit_bounded_shared_call_limit(public_fixture, limit):
    path, pack, output = public_fixture
    job = api().public_job(
        path, pack, pack["identity"]["slots"][0], output / "s0000", output / "q", limit
    )
    assert job["call_limit"] == limit


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 1),
        ("version", 3),
        ("profile", "goldset50-r2"),
        ("profile", None),
        ("call_limit", True),
        ("call_limit", 0),
        ("call_limit", 5551),
        ("call_limit", "5550"),
        ("call_limit", float("inf")),
        ("private", {}),
    ],
)
def test_v2_unknown_fields_profiles_versions_or_excess_budget_are_rejected(
    public_fixture, field, value
):
    from benchmarks.evaluation.live_plan import validate_job

    path, pack, output = public_fixture
    job = api().public_job(
        path, pack, pack["identity"]["slots"][0], output / "s0000", output / "q", 5550
    )
    job[field] = value
    with pytest.raises(ValueError):
        api().validate_job(job)
    with pytest.raises(ValueError):
        validate_job(job)


@pytest.mark.parametrize(
    "mutation", ["unknown", "revision", "source", "trial", "evidence", "path", "environment"]
)
def test_v2_reuses_public_evidence_path_and_environment_validation(public_fixture, mutation):
    path, pack, output = public_fixture
    job = api().public_job(
        path, pack, pack["identity"]["slots"][0], output / "s0000", output / "q", 5550
    )
    if mutation == "unknown":
        job["spec"]["case_id"] = job["slot"]["case_id"] = "not_a_goldset_task"
        job["slot"]["slot"] = "not_a_goldset_task--1--single-shot"
    elif mutation == "revision":
        job["spec"]["revision"] = 99
    elif mutation == "source":
        job["spec"]["source_kind"] = "opensource"
    elif mutation == "trial":
        job["slot"]["trial"] = 4
    elif mutation == "evidence":
        job["evidence"]["failure"]["summary"] = "replaced"
        job["evidence"]["case_id"] = "other-task"
    elif mutation == "path":
        job["output"] = job["repo"]
    else:
        job["environment"]["image_id"] = "changed"
    with pytest.raises(ValueError):
        api().validate_job(job)


def test_legacy_v1_cannot_gain_fifty_task_budget(public_fixture):
    from benchmarks.evaluation.live_plan import public_job, validate_job

    path, pack, output = public_fixture
    original = public_job(
        path, pack, pack["identity"]["slots"][0], output / "s0000", output / "q", 2220
    )
    assert validate_job(original) == original
    changed = copy.deepcopy(original)
    changed["call_limit"] = 2221
    with pytest.raises(ValueError):
        validate_job(changed)


def test_v2_config_cannot_replace_integer_policy_with_boolean(public_fixture):
    path, pack, output = public_fixture
    job = api().public_job(
        path, pack, pack["identity"]["slots"][0], output / "s0000", output / "q", 5550
    )
    job["config"]["max_calls_single_shot"] = True
    with pytest.raises(ValueError):
        api().validate_job(job)
