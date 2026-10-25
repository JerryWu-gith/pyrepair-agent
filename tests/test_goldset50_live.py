"""Controlled fifty-task plans reuse the trusted journal without live operations."""

import copy
import importlib
import importlib.util
import json
from collections import Counter

import pytest

from benchmarks.evaluation.comparison_pack import comparison_config, paired_slots
from benchmarks.evaluation.experiment import digest
from tests.test_comparison_pack import make_prepared
from tests.test_goldset50_dataset import selection
from tests.test_live_comparison import no_credential
from tests.test_live_plan import approval


def api():
    name = "benchmarks.evaluation.goldset_live"
    assert importlib.util.find_spec(name) is not None, "fifty-task live profile missing"
    return importlib.import_module(name)


def frozen_plan_pack(tmp_path):
    cases = selection(tmp_path)
    entries = [
        {
            "id": c.id,
            "revision": c.revision,
            "source_kind": c.source_kind,
            "split": c.split,
            "fingerprint": "a" * 64,
        }
        for c in cases
    ]
    identity = {
        "version": 2,
        "authorization": "offline-only",
        "config": comparison_config("deepseek-flash", 3),
        "runtime": {"source_hash": "owned"},
        "environment": {"lock_path": str(tmp_path / "environment-lock.json")},
        "cases": entries,
        "slots": paired_slots([c.id for c in cases], 3),
    }
    path = tmp_path / "pack"
    path.mkdir()
    pack = {"identity": identity, "identity_hash": digest(identity)}
    (path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    return path, pack


def rewrite_pack(path, pack):
    pack["identity_hash"] = digest(pack["identity"])
    (path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")


def test_fifty_formal_profile_has_exact_groups_pairs_and_bounded_5550_calls(tmp_path):
    from benchmarks.evaluation.live_plan import describe_plan

    path, pack = frozen_plan_pack(tmp_path)
    output = tmp_path / "out"
    plan = api().describe_plan(path, pack, output, "formal", 5550)
    assert plan["kind"] == "pyrepair-goldset50-live-comparison"
    assert plan["profile"] == "goldset50-r1"
    assert plan["mode"] == "formal"
    assert len(plan["slots"]) == len({s["slot"] for s in plan["slots"]}) == 300
    assert Counter(s["method"] for s in plan["slots"]) == {"single-shot": 150, "full-agent": 150}
    assert Counter((e["source_kind"], e["split"]) for e in pack["identity"]["cases"]) == {
        ("synthetic", "dev"): 20,
        ("opensource", "dev"): 2,
        ("opensource", "holdout"): 28,
    }
    assert plan["slots"][:4] == [
        {
            "slot": "case_01--1--single-shot",
            "case_id": "case_01",
            "method": "single-shot",
            "trial": 1,
        },
        {
            "slot": "case_01--1--full-agent",
            "case_id": "case_01",
            "method": "full-agent",
            "trial": 1,
        },
        {
            "slot": "case_01--2--full-agent",
            "case_id": "case_01",
            "method": "full-agent",
            "trial": 2,
        },
        {
            "slot": "case_01--2--single-shot",
            "case_id": "case_01",
            "method": "single-shot",
            "trial": 2,
        },
    ]
    assert plan["maximum_slot_calls"] == plan["call_limit"] == 5550
    assert plan["config"]["provider_retries"] == plan["config"]["sdk_retries"] == 0
    assert not output.exists()
    with pytest.raises(ValueError, match="20-case"):
        describe_plan(path, pack, output, "formal", 2220)


@pytest.mark.parametrize("limit", [True, 0, -1, 5551, "5550", float("inf"), None])
def test_fifty_profile_rejects_nonfinite_noninteger_or_excess_call_limit(tmp_path, limit):
    path, pack = frozen_plan_pack(tmp_path)
    with pytest.raises(ValueError):
        api().describe_plan(path, pack, tmp_path / "out", "formal", limit)


@pytest.mark.parametrize("limit", [1, 2220, 2221, 5550])
def test_fifty_profile_allows_lower_explicit_call_limit(tmp_path, limit):
    path, pack = frozen_plan_pack(tmp_path)
    assert api().describe_plan(path, pack, tmp_path / "out", "formal", limit)["call_limit"] == limit


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "order",
        "source",
        "split",
        "revision",
        "revision_bool",
        "schedule",
        "model",
        "endpoint",
        "trials",
        "authorization",
        "hash",
        "unfrozen",
    ],
)
def test_fifty_profile_rejects_changed_selection_schedule_or_frozen_identity(tmp_path, mutation):
    path, pack = frozen_plan_pack(tmp_path)
    identity = pack["identity"]
    if mutation == "missing":
        identity["cases"].pop()
    elif mutation == "duplicate":
        identity["cases"][-1] = copy.deepcopy(identity["cases"][-2])
    elif mutation == "order":
        identity["cases"].reverse()
    elif mutation in {"source", "split", "revision", "revision_bool"}:
        field, value = {
            "source": ("source_kind", "synthetic"),
            "split": ("split", "dev"),
            "revision": ("revision", 99),
            "revision_bool": ("revision", True),
        }[mutation]
        identity["cases"][-1][field] = value
    elif mutation == "schedule":
        identity["slots"].reverse()
    elif mutation in {"model", "endpoint", "trials"}:
        identity["config"][mutation] = {
            "model": "other",
            "endpoint": "https://other.invalid",
            "trials": 1,
        }[mutation]
    elif mutation == "authorization":
        identity["authorization"] = "live"
    elif mutation == "hash":
        pack["identity_hash"] = "0" * 64
    else:
        identity["runtime"]["source_hash"] = "unfrozen"
    if mutation not in {"hash", "unfrozen"}:
        rewrite_pack(path, pack)
    with pytest.raises(ValueError):
        api().describe_plan(path, pack, tmp_path / "out", "formal", 5550)


@pytest.mark.parametrize("mode", ["smoke", "offline", "unknown"])
def test_fifty_profile_is_formal_only(tmp_path, mode):
    path, pack = frozen_plan_pack(tmp_path)
    with pytest.raises(ValueError):
        api().describe_plan(path, pack, tmp_path / "out", mode, 37)


def test_fifty_profile_rejects_output_overlapping_frozen_pack(tmp_path):
    path, pack = frozen_plan_pack(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        api().describe_plan(path, pack, path / "out", "formal", 5550)


def test_changed_registered_split_counts_cannot_expand_fixed_profile(tmp_path, monkeypatch):
    live = api()
    jobs = importlib.import_module("benchmarks.evaluation.goldset_jobs")
    path, pack = frozen_plan_pack(tmp_path)
    catalog = json.loads(jobs.CATALOG.read_text("utf-8"))
    catalog["entries"][-1]["split"] = "dev"
    changed = tmp_path / "changed-catalog.json"
    changed.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(jobs, "CATALOG", changed)
    pack["identity"]["cases"][-1]["split"] = "dev"
    rewrite_pack(path, pack)
    with pytest.raises(ValueError):
        live.describe_plan(path, pack, tmp_path / "out", "formal", 5550)


def test_fifty_plan_config_is_exact_json_policy_not_boolean_equivalent(tmp_path):
    path, pack = frozen_plan_pack(tmp_path)
    pack["identity"]["config"]["max_calls_single_shot"] = True
    rewrite_pack(path, pack)
    with pytest.raises(ValueError):
        api().describe_plan(path, pack, tmp_path / "out", "formal", 5550)


@pytest.fixture
def owned_live(tmp_path, monkeypatch):
    selected = selection(tmp_path / "selection")

    def fifty(pack, cases, lock):
        cases[:] = selected
        more = next(c for c in cases if c.id == "os_more_seekable_1269")
        (more.root / "regression_opensource_v3.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": [
                        {
                            "id": more.id,
                            "revision": more.revision,
                            "paths": ["tests/test_app.py"],
                            "required": ["tests/test_app.py::test_add"],
                            "timeout_seconds": 15,
                            "core_repeats": 3,
                            "reason": "Owned fixture only",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        def calibration(case, output, **kwargs):
            output.mkdir(parents=True)
            return {
                "status": "valid",
                **(
                    {"extended": {"expected_nodes": ["tests/test_app.py::test_add"]}}
                    if case.id == more.id
                    else {}
                ),
            }

        monkeypatch.setattr(pack, "validate_layered", calibration)

    pack_api, cases, path, _ = make_prepared(tmp_path, monkeypatch, fifty)
    live = api()
    monkeypatch.setattr(live, "verify_goldset_pack", pack_api.verify_pack)
    monkeypatch.setattr(
        "benchmarks.evaluation.docker_runner.DockerTestRunner.assert_environment_verified",
        lambda self: {"environment_hash": "owned-hash", "image_id": "owned-image"},
    )
    monkeypatch.setattr("benchmarks.evaluation.live_comparison._credential", no_credential)
    return live, path, cases


def test_inspection_uses_fixed_verifier_without_reading_key_or_creating_output(
    owned_live, tmp_path
):
    live, path, cases = owned_live
    output = tmp_path / "out"
    plan = live.inspect_execution(path, cases, output, "formal", 5550)
    assert plan["profile"] == "goldset50-r1"
    assert not output.exists()


@pytest.mark.parametrize(
    "failure",
    ["approval", "selection", "runtime", "environment", "evidence", "private", "protected_output"],
)
def test_invalid_fifty_authority_or_assets_fail_before_credentials_and_output(
    owned_live, tmp_path, monkeypatch, failure
):
    live, path, cases = owned_live
    output = tmp_path / "out"
    plan = live.inspect_execution(path, cases, output, "formal", 5550)
    value = approval(plan)
    if failure == "approval":
        value["plan"]["profile"] = "other"
        value["plan_hash"] = digest(value["plan"])
    elif failure == "selection":
        cases.reverse()
    elif failure == "runtime":
        monkeypatch.setattr(
            "benchmarks.evaluation.comparison_pack.runtime_identity",
            lambda: {"source_hash": "changed"},
        )
    elif failure == "environment":
        (tmp_path / "environment-lock.json").write_text("{}", encoding="utf-8")
    elif failure == "evidence":
        (path / "p/c00/evidence.json").write_text("{}", encoding="utf-8")
    elif failure == "private":
        cases[0].gold_patch.write_text("changed", encoding="utf-8")
    else:
        output = cases[0].private / "nested"
    with pytest.raises((ValueError, OSError)):
        live.execute_comparison(
            path, cases, output, "formal", 5550, value, credential_getter=no_credential
        )
    assert not output.exists()


def test_owned_fifty_worker_ordinary_failure_continues_technical_stop_never_retries(
    owned_live, tmp_path
):
    live, path, cases = owned_live
    output = tmp_path / "out"
    plan = live.inspect_execution(path, cases, output, "formal", 5550)
    value = approval(plan)
    jobs = []

    def owned(job):
        jobs.append(job)
        if len(jobs) == 3:
            raise RuntimeError("owned infrastructure stop")
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    result = live.execute_comparison(
        path,
        cases,
        output,
        "formal",
        5550,
        value,
        offline_executor=owned,
        credential_getter=no_credential,
    )
    assert result["planned"] == 300
    assert result["finished"] == 3
    assert result["unrun"] == 297
    assert [r["status"] for r in result["rows"][:3]] == ["failed", "failed", "technical_error"]
    assert [j["slot"]["slot"] for j in jobs] == [
        "case_01--1--single-shot",
        "case_01--1--full-agent",
        "case_01--2--full-agent",
    ]
    assert all(
        j["version"] == 2 and j["profile"] == "goldset50-r1" and j["call_limit"] == 5550
        for j in jobs
    )
    assert json.loads((output / "q/budget.json").read_text("utf-8"))["limit"] == 5550
    assert result["real_model_trials"] == 0
    assert all(g["core_acceptance_rate"] is None for g in result["groups"])
    timings = [(output / f"s{i:04d}/g/grading-time.json").read_bytes() for i in range(2)]
    assert all(set(json.loads(raw)) == {"duration_seconds"} for raw in timings)
    assert all(json.loads(raw)["duration_seconds"] >= 0 for raw in timings)
    assert all(
        "duration_seconds" not in json.loads((output / f"s{i:04d}/grade.json").read_text("utf-8"))
        for i in range(2)
    )
    before = (output / "journal.jsonl").read_bytes()

    def forbidden(job):
        pytest.fail("technical terminal cannot be retried")

    again = live.execute_comparison(
        path,
        cases,
        output,
        "formal",
        5550,
        value,
        resume=True,
        offline_executor=forbidden,
        credential_getter=no_credential,
    )
    assert again == result
    assert (output / "journal.jsonl").read_bytes() == before
    assert [(output / f"s{i:04d}/g/grading-time.json").read_bytes() for i in range(2)] == timings
    assert json.loads((output / "summary.json").read_text("utf-8")) == result


@pytest.mark.parametrize(
    "failure", ["identity", "missing_budget", "stale_writer", "unknown_worker"]
)
def test_fifty_resume_rejects_unknown_stale_or_conflicting_state_before_key(
    owned_live, tmp_path, failure
):
    from benchmarks.evaluation.worker_supervisor import WorkerError

    live, path, cases = owned_live
    output = tmp_path / "out"
    plan = live.inspect_execution(path, cases, output, "formal", 5550)
    value = approval(plan)

    def stop(job):
        raise RuntimeError("owned technical stop")

    live.execute_comparison(
        path,
        cases,
        output,
        "formal",
        5550,
        value,
        offline_executor=stop,
        credential_getter=no_credential,
    )
    if failure == "identity":
        (output / "execution.json").write_text("{}", encoding="utf-8")
    elif failure == "missing_budget":
        (output / "q/budget.json").unlink()
    elif failure == "stale_writer":
        (output / "writer.lock").write_text("unknown", encoding="utf-8")
    else:
        (output / "s0000/job.json").write_text("{}", encoding="utf-8")
        (output / "s0000/supervision.json").write_text("{}", encoding="utf-8")
    with pytest.raises((ValueError, OSError, WorkerError)):
        live.execute_comparison(
            path,
            cases,
            output,
            "formal",
            5550,
            value,
            resume=True,
            offline_executor=stop,
            credential_getter=no_credential,
        )


def test_second_fifty_verification_cannot_rebind_authorized_pack(owned_live, tmp_path, monkeypatch):
    live, path, cases = owned_live
    output = tmp_path / "out"
    value = approval(live.inspect_execution(path, cases, output, "formal", 5550))
    original = live.verify_goldset_pack
    count = 0

    def drift(*args):
        nonlocal count
        pack = original(*args)
        count += 1
        if count == 2:
            pack["identity"]["runtime"]["source_hash"] = "changed-between-checks"
            pack["identity_hash"] = digest(pack["identity"])
        return pack

    monkeypatch.setattr(live, "verify_goldset_pack", drift)
    with pytest.raises(ValueError, match="authorization"):
        live.execute_comparison(
            path, cases, output, "formal", 5550, value, credential_getter=no_credential
        )
    assert not output.exists()


@pytest.mark.parametrize("boundary", ["verification", "job"])
def test_per_slot_profile_hooks_fail_closed_before_credential(
    owned_live, tmp_path, monkeypatch, boundary
):
    from benchmarks.evaluation import goldset_jobs

    live, path, cases = owned_live
    output = tmp_path / "out"
    value = approval(live.inspect_execution(path, cases, output, "formal", 5550))
    original = live.verify_goldset_pack
    count = 0

    def drift(*args):
        nonlocal count
        pack = original(*args)
        count += 1
        if count == 3:
            raise ValueError("changed-before-slot")
        return pack

    def bad_job(*args):
        raise ValueError("changed-public-job")

    if boundary == "verification":
        monkeypatch.setattr(live, "verify_goldset_pack", drift)
    else:
        monkeypatch.setattr(goldset_jobs, "public_job", bad_job)
    result = live.execute_comparison(
        path, cases, output, "formal", 5550, value, credential_getter=no_credential
    )
    assert result["finished"] == 1
    assert result["rows"][0]["status"] == "technical_error"
    assert result["unrun"] == 299


def test_shared_grader_emits_separate_monotonic_duration_without_rewriting_on_resume(
    tmp_path, monkeypatch
):
    from benchmarks.evaluation import live_comparison as controller
    from tests.test_live_comparison import live_fixture

    path, cases = live_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "benchmarks.evaluation.docker_runner.DockerTestRunner.assert_environment_verified",
        lambda self: {"environment_hash": "owned-hash", "image_id": "owned-image"},
    )
    ticks = iter([10.0, 10.25, 20.0, 20.5])
    monkeypatch.setattr(controller, "monotonic", lambda: next(ticks), raising=False)
    output = tmp_path / "out"
    value = approval(controller.inspect_execution(path, cases, output, "smoke", 37))

    def no_patch(job):
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    controller.execute_comparison(
        path,
        cases,
        output,
        "smoke",
        37,
        value,
        offline_executor=no_patch,
        credential_getter=no_credential,
    )
    timing = output / "s0000/g/grading-time.json"
    assert json.loads(timing.read_text("utf-8")) == {"duration_seconds": 0.25}
    before = timing.read_bytes()
    controller.execute_comparison(
        path,
        cases,
        output,
        "smoke",
        37,
        value,
        resume=True,
        offline_executor=no_patch,
        credential_getter=no_credential,
    )
    assert timing.read_bytes() == before


@pytest.mark.parametrize("checkpoint", ["completed", "partial"])
def test_interrupted_grading_resume_keeps_missing_original_timing_unknown(
    tmp_path, monkeypatch, checkpoint
):
    from benchmarks.evaluation import layered_grading
    from benchmarks.evaluation import live_comparison as controller
    from tests.test_live_comparison import live_fixture

    path, cases = live_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "benchmarks.evaluation.docker_runner.DockerTestRunner.assert_environment_verified",
        lambda self: {"environment_hash": "owned-hash", "image_id": "owned-image"},
    )
    output = tmp_path / "out"
    value = approval(controller.inspect_execution(path, cases, output, "smoke", 37))
    original = controller.grade_layered
    core = layered_grading.grade_patch

    def interrupt_core(*args, **kwargs):
        raise KeyboardInterrupt("owned partial grading interruption")

    def interrupt_completed(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("owned interruption before timing persistence")

    if checkpoint == "completed":
        monkeypatch.setattr(controller, "grade_layered", interrupt_completed)
    else:
        monkeypatch.setattr(layered_grading, "grade_patch", interrupt_core)

    def no_patch(job):
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    with pytest.raises(KeyboardInterrupt):
        controller.execute_comparison(
            path,
            cases,
            output,
            "smoke",
            37,
            value,
            offline_executor=no_patch,
            credential_getter=no_credential,
        )
    timing = output / "s0000/g/grading-time.json"
    assert not timing.exists()
    assert (output / "s0000/g/identity.json").exists()
    monkeypatch.setattr(controller, "grade_layered", original)
    monkeypatch.setattr(layered_grading, "grade_patch", core)
    resumed = controller.execute_comparison(
        path,
        cases,
        output,
        "smoke",
        37,
        value,
        resume=True,
        offline_executor=no_patch,
        credential_getter=no_credential,
    )
    assert resumed["finished"] == (2 if checkpoint == "completed" else 1)
    assert not timing.exists()
