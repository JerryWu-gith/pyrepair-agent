"""Execution authority binds immutable facts; describing a plan grants nothing."""

import copy
import json

import pytest

from benchmarks.evaluation.comparison_pack import comparison_config, paired_slots
from benchmarks.evaluation.experiment import digest
from tests.test_comparison_pack import make_prepared


def owned_pack(tmp_path):
    entries = [
        {"id": f"case_{n:02d}", "revision": 1, "source_kind": "synthetic"} for n in range(18)
    ] + [
        {"id": "os_more_seekable_1269", "revision": 2, "source_kind": "opensource"},
        {"id": "os_boltons_addlist_458", "revision": 2, "source_kind": "opensource"},
    ]
    identity = {
        "version": 2,
        "authorization": "offline-only",
        "config": comparison_config("deepseek-flash", 3),
        "runtime": {"source_hash": "a" * 64},
        "environment": {"lock_path": str(tmp_path / "environment-lock.json")},
        "cases": entries,
        "slots": paired_slots([e["id"] for e in entries], 3),
    }
    value = {"identity": identity, "identity_hash": digest(identity)}
    path = tmp_path / "pack"
    path.mkdir()
    (path / "pack.json").write_text(json.dumps(value), encoding="utf-8")
    return path, value


def approval(plan):
    return {
        "version": 1,
        "approved": True,
        "human_confirmation": "Owned offline test only; not a paid authorization",
        "plan": copy.deepcopy(plan),
        "plan_hash": digest(plan),
    }


def test_inspection_is_read_only_and_smoke_preserves_pair_order(tmp_path):
    from benchmarks.evaluation.live_plan import describe_plan, validate_authorization

    path, pack = owned_pack(tmp_path)
    output = tmp_path / "smoke"
    plan = describe_plan(path, pack, output, "smoke", 37)
    assert plan["slots"] == [
        {
            "slot": "os_more_seekable_1269--1--single-shot",
            "case_id": "os_more_seekable_1269",
            "trial": 1,
            "method": "single-shot",
        },
        {
            "slot": "os_more_seekable_1269--1--full-agent",
            "case_id": "os_more_seekable_1269",
            "trial": 1,
            "method": "full-agent",
        },
    ]
    assert plan["call_limit"] == plan["maximum_slot_calls"] == 37
    assert not output.exists()
    assert "approved" not in plan
    assert validate_authorization(approval(plan), plan) == plan


@pytest.mark.parametrize(
    "field,changed",
    [
        ("call_limit", 38),
        ("output", "another-output"),
        ("mode", "formal"),
        ("pack_hash", "b" * 64),
        ("pack_file_hash", "b" * 64),
        ("config", {"model": "another-model"}),
        ("runtime", {"source_hash": "b" * 64}),
        ("environment", {"image_id": "another-image"}),
        ("slot_limits", {"single-shot": 2, "full-agent": 36}),
    ],
)
def test_recomputed_approval_digest_does_not_authorize_a_different_plan(tmp_path, field, changed):
    from benchmarks.evaluation.live_plan import describe_plan, validate_authorization

    path, pack = owned_pack(tmp_path)
    expected = describe_plan(path, pack, tmp_path / "output", "smoke", 37)
    changed_plan = copy.deepcopy(expected)
    changed_plan[field] = changed
    with pytest.raises(ValueError, match="authorization"):
        validate_authorization(approval(changed_plan), expected)


@pytest.mark.parametrize("mutation", ["order", "missing", "duplicate", "not_approved", "extra"])
def test_approval_requires_exact_slots_and_explicit_human_record(tmp_path, mutation):
    from benchmarks.evaluation.live_plan import describe_plan, validate_authorization

    path, pack = owned_pack(tmp_path)
    expected = describe_plan(path, pack, tmp_path / "output", "smoke", 37)
    value = approval(expected)
    if mutation == "order":
        value["plan"]["slots"].reverse()
    elif mutation == "missing":
        value["plan"]["slots"].pop()
    elif mutation == "duplicate":
        value["plan"]["slots"][1] = value["plan"]["slots"][0]
    elif mutation == "not_approved":
        value["approved"] = False
    else:
        value["api_key"] = "not-allowed"
    value["plan_hash"] = digest(value["plan"])
    with pytest.raises(ValueError, match="authorization"):
        validate_authorization(value, expected)


@pytest.mark.parametrize("limit", [True, 0, -1, 38, "37"])
def test_invalid_or_excessive_smoke_call_limit_is_rejected(tmp_path, limit):
    from benchmarks.evaluation.live_plan import describe_plan

    path, pack = owned_pack(tmp_path)
    with pytest.raises(ValueError):
        describe_plan(path, pack, tmp_path / "output", "smoke", limit)


@pytest.mark.parametrize("mutation", ["model", "endpoint", "revision", "slots", "identity"])
def test_plan_does_not_silently_rebind_wrong_frozen_facts(tmp_path, mutation):
    from benchmarks.evaluation.live_plan import describe_plan

    path, pack = owned_pack(tmp_path)
    if mutation == "model":
        pack["identity"]["config"]["model"] = "deepseek-v4-flash"
    elif mutation == "endpoint":
        pack["identity"]["config"]["endpoint"] = "https://other.invalid"
    elif mutation == "revision":
        pack["identity"]["cases"][18]["revision"] = 1
    elif mutation == "slots":
        pack["identity"]["slots"].reverse()
    else:
        pack["identity_hash"] = "0" * 64
    if mutation != "identity":
        pack["identity_hash"] = digest(pack["identity"])
        (path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError):
        describe_plan(path, pack, tmp_path / "output", "smoke", 37)


def test_formal_plan_has_full_120_slots_and_bounded_2220_maximum(tmp_path):
    from benchmarks.evaluation.live_plan import describe_plan

    path, pack = owned_pack(tmp_path)
    plan = describe_plan(path, pack, tmp_path / "formal", "formal", 2220)
    assert len(plan["slots"]) == 120
    assert plan["maximum_slot_calls"] == 2220
    assert plan["config"]["provider_retries"] == plan["config"]["sdk_retries"] == 0
    assert plan["config"]["worker_timeout"] == 1800
    with pytest.raises(ValueError):
        describe_plan(path, pack, path / "nested", "formal", 2220)


def test_public_job_only_carries_frozen_public_files_and_shared_quota(tmp_path, monkeypatch):
    from benchmarks.evaluation.live_plan import public_job, validate_job

    _, cases, path, lock = make_prepared(tmp_path, monkeypatch)
    pack = json.loads((path / "pack.json").read_text("utf-8"))
    output = tmp_path / "output"
    slot = pack["identity"]["slots"][0]
    job = public_job(path, pack, slot, output / "s0000", output / "quota", 37)
    assert validate_job(job) == job
    assert set(job) == {
        "version",
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
    assert job["environment"]["lock_path"] == str(lock.absolute())
    assert job["slot"]["method"] == "single-shot"
    assert str(cases[0].private) not in json.dumps(job)
    assert "hidden_tests" not in json.dumps(job)
    assert "api_key" not in json.dumps(job)
    assert "fingerprint" not in json.dumps(job)
    assert "calibration" not in json.dumps(job)
    assert not output.exists()
    job["spec"]["case_id"] = "other-task"
    with pytest.raises(ValueError):
        validate_job(job)


def test_replaced_public_evidence_after_initial_verification_is_not_a_frozen_job(
    tmp_path, monkeypatch
):
    from benchmarks.evaluation.live_plan import public_job

    _, _, path, _ = make_prepared(tmp_path, monkeypatch)
    pack = json.loads((path / "pack.json").read_text("utf-8"))
    evidence_path = path / "p/c00/evidence.json"
    changed = json.loads(evidence_path.read_text("utf-8"))
    changed["failure"]["summary"] = "coherently replaced public evidence"
    evidence_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        public_job(
            path, pack, pack["identity"]["slots"][0], tmp_path / "o/s0000", tmp_path / "o/q", 37
        )
