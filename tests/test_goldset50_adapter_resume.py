"""Adapter continuation: owned evidence, no containers or provider clients."""

import copy
import importlib
import importlib.util
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from benchmarks.evaluation.agent_input import prepare_agent_input
from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.comparison_evidence import capture_evidence
from benchmarks.evaluation.comparison_pack import file_hash, paired_slots
from benchmarks.evaluation.experiment import digest
from tests.evaluation_helpers import make_case
from tests.test_comparison_evidence import OwnedRunner, failed_run
from tests.test_live_comparison import no_credential
from tests.test_live_plan import approval


def api():
    assert importlib.util.find_spec("scripts.goldset50_adapter_resume") is not None, (
        "adapter-fixed continuation is missing"
    )
    return importlib.import_module("scripts.goldset50_adapter_resume")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_exact_suffix_does_not_regenerate_133_completed_slots():
    slots = paired_slots([f"case_{n:02d}" for n in range(50)], 3)
    suffix = api()._suffix(slots, 506)
    assert len(suffix) == 167
    assert suffix[0]["slot"] == "case_22--1--full-agent"
    assert sum(s["method"] == "full-agent" for s in suffix) == 84
    assert sum(s["method"] == "single-shot" for s in suffix) == 83
    assert sum(36 if s["method"] == "full-agent" else 1 for s in suffix) == 3107
    with pytest.raises(ValueError):
        api()._suffix(slots, 507)


@pytest.mark.parametrize("mutation", ["extra", "missing", "other", "cli", "runtime"])
def test_only_comparison_evidence_source_may_change(mutation):
    old = {"benchmarks/evaluation/comparison_evidence.py": "old", "src/a.py": "same"}
    runtime = {"source_hash": digest(old), "python": "same", "comparison_cli_hash": "same"}
    checkpoint = {
        "source_files": old,
        "runtime": runtime,
        "allowed_runtime_changes": ["benchmarks/evaluation/comparison_evidence.py"],
    }
    current = {**old, "benchmarks/evaluation/comparison_evidence.py": "new"}
    now = {**runtime, "source_hash": digest(current)}
    if mutation == "extra":
        current["src/new.py"] = "new"
    elif mutation == "missing":
        del current["src/a.py"]
    elif mutation == "other":
        current["src/a.py"] = "changed"
    elif mutation == "cli":
        now["comparison_cli_hash"] = "changed"
    else:
        now["python"] = "changed"
    with pytest.raises(ValueError, match="source|runtime"):
        api()._source_delta(checkpoint, current, now)


def test_source_delta_reconstructs_old_and_new_runtime():
    old = {"benchmarks/evaluation/comparison_evidence.py": "old", "src/a.py": "same"}
    current = {**old, "benchmarks/evaluation/comparison_evidence.py": "new"}
    runtime = {"source_hash": digest(old), "python": "same"}
    checkpoint = {
        "source_files": old,
        "runtime": runtime,
        "allowed_runtime_changes": ["benchmarks/evaluation/comparison_evidence.py"],
    }
    assert api()._source_delta(
        checkpoint, current, {**runtime, "source_hash": digest(current)}
    ) == {"benchmarks/evaluation/comparison_evidence.py": {"before": "old", "after": "new"}}


@pytest.fixture
def preflight(tmp_path):
    root = tmp_path / "pf"
    case = load_cases(make_case(tmp_path / "assets"))[0]
    repo = tmp_path / "pack/p/c00/r"
    spec = prepare_agent_input(case, repo)
    evidence = capture_evidence(repo, spec, OwnedRunner())
    save(repo.parent / "spec.json", spec.to_dict())
    save(repo.parent / "evidence.json", evidence)
    entry = {
        "id": case.id,
        "public": "p/c00",
        "fingerprint": "owned-fingerprint",
        "spec_hash": file_hash(repo.parent / "spec.json"),
        "evidence_hash": file_hash(repo.parent / "evidence.json"),
    }
    identity = {
        "cases": [entry],
        "runtime": {"source_hash": "owned"},
        "environment": {"verified_hash": "owned-environment"},
    }
    pack = {"identity": identity, "identity_hash": digest(identity)}
    save(tmp_path / "pack/pack.json", pack)
    observed = root / "c00/observed.json"
    adapter = root / "c00/t/test-0001-owned/adapter-result.json"
    save(observed, asdict(failed_run()))
    save(
        adapter,
        {
            "status": "failed",
            "pytest_exit_code": 1,
            "output_semantics": "validated_combined_pytest_log",
            "identity": {"environment_hash": "owned-environment"},
            "public_input_hash": spec.public_input_hash,
        },
    )
    receipt = {
        "version": 1,
        "kind": "public-baseline-preflight",
        "pack_path": str((tmp_path / "pack").resolve()),
        "pack_file_hash": file_hash(tmp_path / "pack/pack.json"),
        "pack_identity_hash": pack["identity_hash"],
        "runtime_hash": digest(identity["runtime"]),
        "expected_cases": [case.id],
        "no_model_calls": True,
        "results": [
            {
                "case_id": case.id,
                "fingerprint": entry["fingerprint"],
                "spec_hash": entry["spec_hash"],
                "evidence_hash": entry["evidence_hash"],
                "public_input_hash": spec.public_input_hash,
                "status": "matched",
                "observed": "c00/observed.json",
                "observed_hash": file_hash(observed),
                "adapter_result": "c00/t/test-0001-owned/adapter-result.json",
                "adapter_result_hash": file_hash(adapter),
            }
        ],
    }
    save(root / "receipt.json", receipt)
    return root / "receipt.json", tmp_path / "pack", pack, [case.id]


def test_preflight_reparses_saved_observation_without_grading(preflight):
    result = api()._preflight(*preflight)
    assert result["case_count"] == 1
    assert len(result["critical_hashes"]) == 3


@pytest.mark.parametrize(
    "mutation",
    ["incomplete", "calls", "hash", "escape", "technical", "baseline", "collection", "adapter"],
)
def test_preflight_fails_closed_even_when_observed_hash_is_rebound(preflight, mutation):
    receipt_path, pack_path, pack, expected = preflight
    receipt = json.loads(receipt_path.read_text())
    row = receipt["results"][0]
    observed = receipt_path.parent / row["observed"]
    run = failed_run()
    if mutation == "incomplete":
        receipt["results"] = []
    elif mutation == "calls":
        receipt["no_model_calls"] = False
    elif mutation == "hash":
        row["observed_hash"] = "0" * 64
    elif mutation == "escape":
        row["observed"] = "../outside.json"
    elif mutation == "adapter":
        adapter = receipt_path.parent / row["adapter_result"]
        value = json.loads(adapter.read_text())
        value["identity"]["environment_hash"] = "changed"
        save(adapter, value)
        row["adapter_result_hash"] = file_hash(adapter)
    else:
        if mutation == "technical":
            run = replace(run, timed_out=True)
        elif mutation == "collection":
            run = replace(run, failures=(replace(run.failures[0], phase="collection"),))
        else:
            run = failed_run("assert 100 == 5")
        save(observed, asdict(run))
        row["observed_hash"] = file_hash(observed)
    save(receipt_path, receipt)
    with pytest.raises(ValueError):
        api()._preflight(receipt_path, pack_path, pack, expected)


def test_invalid_authority_never_reads_key_or_creates_output(tmp_path):
    descriptor = {"plan": {"owned": True}, "output": str(tmp_path / "output")}
    with pytest.raises(ValueError, match="authorization"):
        api().execute_resume(descriptor, None, credential_getter=no_credential)
    assert not (tmp_path / "output").exists()


def test_cli_technical_summary_returns_two(tmp_path, monkeypatch):
    module = api()
    save(tmp_path / "descriptor.json", {"output": str(tmp_path / "stage")})
    save(tmp_path / "auth.json", {})
    monkeypatch.setattr(
        module, "execute_resume", lambda *a: {"rows": [{"status": "technical_error"}]}
    )
    assert (
        module.main(
            [
                "execute",
                "--descriptor",
                str(tmp_path / "descriptor.json"),
                "--authorization",
                str(tmp_path / "auth.json"),
            ]
        )
        == 2
    )


def test_cli_refuses_stage_output_overlapping_its_approval(tmp_path, monkeypatch):
    module = api()
    output = tmp_path / "stage"
    save(tmp_path / "descriptor.json", {"output": str(output)})
    save(output / "auth.json", {})

    def forbidden(*args):
        pytest.fail("an overlapping approval must be refused before execution")

    monkeypatch.setattr(module, "execute_resume", forbidden)
    assert (
        module.main(
            [
                "execute",
                "--descriptor",
                str(tmp_path / "descriptor.json"),
                "--authorization",
                str(output / "auth.json"),
            ]
        )
        == 2
    )


def test_historical_fault_with_model_calls_is_not_regenerable():
    module = api()
    slot = {"slot": "c--1--full-agent", "case_id": "c", "trial": 1, "method": "full-agent"}
    record = {
        **slot,
        "status": "technical_error",
        "candidate": None,
        "grade": None,
        "error_type": "WorkerError",
    }
    with pytest.raises(ValueError, match="zero-call"):
        module._zero_call_fault(record, {"one": {"slot": slot["slot"]}})
    module._zero_call_fault(record, {})


def test_historical_authority_is_bound_to_execution_bytes(tmp_path):
    module = api()
    plan = {"owned": True}
    auth = approval(plan)
    save(tmp_path / "approval.json", auth)
    save(
        tmp_path / "execution.json",
        {
            "version": 1,
            "plan_hash": digest(plan),
            "authorization_hash": "0" * 64,
            "offline_owned_executor": False,
        },
    )
    with pytest.raises(ValueError, match="execution"):
        module._authority(tmp_path, tmp_path / "approval.json", plan)


@pytest.mark.parametrize(
    "target",
    [
        "dataset",
        "original_pack",
        "new_pack",
        "original_output",
        "recovery_output",
        "preflight",
        "checkpoint",
    ],
)
def test_output_may_not_alias_or_contain_any_source(tmp_path, target):
    paths = {n: tmp_path / n for n in api().PATH_FIELDS}
    paths["output"] = paths[target] / "child"
    with pytest.raises(ValueError, match="overlap"):
        api()._protected(paths, [], {"environment": {"lock_path": str(tmp_path / "lock.json")}})


def test_saved_merge_uses_full_denominator_and_does_not_count_old_technical_events():
    report = importlib.import_module("scripts.goldset50_adapter_report")
    slots = paired_slots(["a", "b"], 3)
    pack = {
        "identity": {
            "version": 2,
            "slots": slots,
            "cases": [{"id": n, "source_kind": "synthetic"} for n in ("a", "b")],
        },
        "identity_hash": "owned",
    }

    def record(slot):
        return {
            **slot,
            "simulation": False,
            "status": "core_passed",
            "core_passed": True,
            "fully_verified": True,
            "candidate": {"duration_seconds": None},
            "grade": {
                "version": 2,
                "status": "core_passed",
                "extended": {"status": "not_applicable"},
            },
        }

    prior = [record(slots[0]), record(slots[1])]
    stage = [record(slots[2])]
    result = report._combine(pack, prior, stage, {"reserved_calls": 7})
    assert result["planned"] == 12
    assert result["finished"] == 3
    assert result["unrun"] == 9
    assert result["groups"][0]["core_accepted"] == 1
    assert result["groups"][1]["core_accepted"] == 2
    assert all(g["core_acceptance_rate"] is None for g in result["groups"])
    assert result["rows"][0]["duration_seconds"] is None
    full = report._combine(
        pack, [record(s) for s in slots[:2]], [record(s) for s in slots[2:]], {"reserved_calls": 14}
    )
    assert full["finished"] == full["planned"] == 12
    assert full["unrun"] == 0
    assert [g["core_acceptance_rate"] for g in full["groups"]] == [1.0, 1.0]


def test_compact_tree_receipt_keeps_full_inventory_in_bounded_chunks(tmp_path):
    report = importlib.import_module("scripts.goldset50_adapter_report")
    files = {f"folder/{n:05d}.json": "a" * 64 for n in range(2301)}
    tree = {"path": "owned-root", "files": files, "hash": digest(files)}
    receipt = report._save_tree(tree, tmp_path, "owned")
    assert receipt["file_count"] == 2301
    assert receipt["hash"] == digest(files)
    assert len(receipt["chunks"]) == 3
    assert "files" not in receipt
    restored = {}
    for chunk in receipt["chunks"]:
        path = tmp_path / chunk["path"]
        assert path.stat().st_size < 4 * 1024 * 1024
        assert file_hash(path) == chunk["sha256"]
        restored.update(json.loads(path.read_text())["files"])
    assert restored == files


@pytest.fixture(scope="module")
def owned_history(tmp_path_factory):
    """One file-only historical checkpoint, not 300 executor invocations."""
    import shutil

    from benchmarks.evaluation import comparison_pack, goldset_live, goldset_pack, live_comparison
    from benchmarks.evaluation.cases import case_fingerprint
    from benchmarks.evaluation.comparison_journal import _record
    from benchmarks.evaluation.goldset_dataset import assemble_dataset, verify_dataset
    from scripts import goldset50_recovery as recovery
    from tests.test_catalog_calibration import ENVIRONMENT, owned_report
    from tests.test_goldset50_dataset import materialized_selection
    from tests.test_goldset50_recovery import saved_grade

    base = tmp_path_factory.mktemp("ah")
    mp = pytest.MonkeyPatch()
    mp.setattr(
        "benchmarks.evaluation.docker_runner.DockerTestRunner.assert_environment_verified",
        lambda self: {"environment_hash": ENVIRONMENT, "image_id": "owned-image"},
    )
    mp.setattr(comparison_pack, "DockerAgentTestRunner", lambda *a: OwnedRunner())
    dataset = base / "d"
    assemble_dataset([materialized_selection(base / "m")], dataset)
    cases = verify_dataset(dataset)
    _, _, template = owned_report(base / "ct")
    for case in cases:
        save(
            base / "c" / case.id / "validation.json",
            {**copy.deepcopy(template), "case_id": case.id, "fingerprint": case_fingerprint(case)},
        )
    lock = base / "lock.json"
    save(lock, {"image_id": "owned-image"})
    save(base / "environment-check.json", {})
    new_path, old_path = base / "n", base / "o"
    goldset_pack.prepare_goldset_pack(dataset, new_path, lock, [base / "c"])
    new = goldset_pack.verify_goldset_pack(new_path, cases)
    shutil.copytree(new_path, old_path)
    old = copy.deepcopy(new)
    sources = api()._source_files()
    sources["benchmarks/evaluation/comparison_evidence.py"] = "a" * 64
    old["identity"]["runtime"]["source_hash"] = digest(sources)
    old["identity_hash"] = digest(old["identity"])
    save(old_path / "pack.json", old)
    original, stage = base / "r0", base / "r1"
    old_plan = goldset_live.describe_plan(old_path, old, original, "formal", 5550)
    auth = approval(old_plan)
    auth_path = base / "auth.json"
    save(auth_path, auth)

    def identity(root, plan, authorization):
        save(
            root / "execution.json",
            {
                "version": 1,
                "plan_hash": digest(plan),
                "authorization_hash": digest(authorization),
                "offline_owned_executor": False,
            },
        )
        selected = live_comparison._selected_pack(old, plan)
        save(root / "run.json", {"pack": selected["identity_hash"], "simulation": False})
        return selected

    def histories(root, selected, count, fault=None):
        events = []
        for index, slot in enumerate(selected["identity"]["slots"][:count]):
            folder = root / f"s{index:04d}"
            candidate, grade = None, None
            pieces = [("started", None)]
            if fault != "worker" or index != count - 1:
                candidate = {
                    "status": "candidate",
                    "patch": "owned patch",
                    "internal_success": True,
                    "duration_seconds": 1.25,
                }
                save(folder / "candidate.json", candidate)
                entry = next(e for e in old["identity"]["cases"] if e["id"] == slot["case_id"])
                grade = saved_grade(
                    folder / "g",
                    entry,
                    "owned patch",
                    "environment_error"
                    if fault == "environment" and index == count - 1
                    else "passed",
                )
                save(folder / "grade.json", grade)
                if index == 0:
                    save(folder / "g/grading-time.json", {"duration_seconds": 0.5})
                pieces.extend(
                    (
                        ("candidate", file_hash(folder / "candidate.json")),
                        ("grade", file_hash(folder / "grade.json")),
                    )
                )
            pieces.append(
                (
                    "terminal",
                    _record(
                        slot,
                        candidate,
                        grade,
                        False,
                        "WorkerError" if fault == "worker" and index == count - 1 else None,
                    ),
                )
            )
            events.extend(
                {
                    "pack": selected["identity_hash"],
                    "slot": slot["slot"],
                    "event": kind,
                    "data": data,
                }
                for kind, data in pieces
            )
        (root / "journal.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
        )

    def calls(root, slots, count, limit):
        save(root / "q/budget.json", {"version": 1, "limit": limit})
        events, number = [], 0
        for slot in slots:
            for _ in range(min(count - number, 36 if slot["method"] == "full-agent" else 1)):
                number += 1
                events.extend(
                    (
                        {
                            "event": "reserved",
                            "call_id": number,
                            "slot": slot["slot"],
                            "role": "repair" if slot["method"] == "full-agent" else "single-shot",
                            "slot_limit": 36 if slot["method"] == "full-agent" else 1,
                        },
                        {
                            "event": "response",
                            "call_id": number,
                            "prompt_tokens": 10,
                            "completion_tokens": 2,
                        },
                    )
                )
        (root / "q/calls.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
        )

    histories(original, identity(original, old_plan, auth), 130, "environment")
    calls(original, old_plan["slots"][:130], 503, 5550)
    regrade = base / "rg"
    failed = old_plan["slots"][129]
    grade = saved_grade(
        regrade,
        next(e for e in old["identity"]["cases"] if e["id"] == failed["case_id"]),
        "owned patch",
    )
    old_tree, regrade_tree = recovery.tree_identity(original), recovery.tree_identity(regrade)
    cp = {
        "terminal_records": 130,
        "normal_records": 129,
        "calls": 503,
        "responses": 503,
        "original_budget": 5550,
        "original_plan_hash": digest(old_plan),
        "original_authorization_hash": digest(auth),
        "original_tree": old_tree,
        "regrade_tree": regrade_tree,
        "candidate_sha256": file_hash(original / "s0129/candidate.json"),
        "regrade_sha256": file_hash(regrade / "result.json"),
        "regrade_status": grade["status"],
        "critical_hashes": {str(auth_path): file_hash(auth_path)},
    }
    cp["original_technical_error"] = recovery._old_records(
        original, live_comparison._selected_pack(old, old_plan)
    )[-1]
    plan = goldset_live.describe_plan(old_path, old, stage, "formal", 5550)
    plan.update(
        kind="pyrepair-goldset50-controlled-recovery",
        slots=plan["slots"][129:],
        call_limit=3145,
        maximum_slot_calls=3145,
        new_generation_slots=170,
        checkpoint_hash=digest(cp),
        original_plan_hash=digest(old_plan),
        original_budget=5550,
        previous_calls=503,
        cumulative_maximum_calls=3648,
        recovery_sources=recovery.recovery_sources(),
        reused_first_slot={
            "slot": recovery.FAILED_SLOT,
            "mode": "saved-candidate-and-validated-regrade",
            "new_model_calls": 0,
        },
    )
    rd = {
        "version": 1,
        "dataset": str(dataset),
        "pack": str(old_path),
        "original_output": str(original),
        "original_authorization": str(auth_path),
        "regrade": str(regrade),
        "output": str(stage),
        "checkpoint": cp,
        "plan": plan,
    }
    rd_path, ra_path = base / "rd.json", base / "ra.json"
    save(rd_path, rd)
    ra = approval(plan)
    save(ra_path, ra)
    histories(stage, identity(stage, plan, ra), 5, "worker")
    calls(stage, plan["slots"][1:4], 3, 3145)
    save(stage / "s0004/job.json", {"owned": True})
    save(
        stage / "s0004/supervision.json",
        {
            "job_hash": digest({"owned": True}),
            "status": "worker_error",
            "returncode": 2,
            "cleanup": {"status": "clean"},
        },
    )
    checkpoint = {
        "version": 1,
        "allowed_runtime_changes": ["benchmarks/evaluation/comparison_evidence.py"],
        "source_files": sources,
        "runtime": old["identity"]["runtime"],
        "recovery_sources": recovery.recovery_sources(),
        "cli_files": {
            n: file_hash(comparison_pack.__file__ and Path(comparison_pack.__file__).parents[1] / n)
            for n in ("run_comparison.py", "run_goldset50.py", "run_live_comparison.py")
        },
        "artifacts": {
            str(p): file_hash(p) for p in (rd_path, ra_path, auth_path, old_path / "pack.json")
        },
        "previous_calls": 506,
        "planned_normal_prefix": 133,
        "planned_suffix": 167,
        "new_call_maximum": 3107,
        "original_call_limit": 5550,
    }
    cp_path = base / "checkpoint.json"
    save(cp_path, checkpoint)
    expected = [
        e["id"]
        for e in new["identity"]["cases"]
        if e["id"] in {s["case_id"] for s in new["identity"]["slots"][133:]}
    ]
    receipt = {
        "version": 1,
        "kind": "public-baseline-preflight",
        "pack_path": str(new_path),
        "pack_file_hash": file_hash(new_path / "pack.json"),
        "pack_identity_hash": new["identity_hash"],
        "runtime_hash": digest(new["identity"]["runtime"]),
        "expected_cases": expected,
        "results": [],
        "no_model_calls": True,
    }
    pf = base / "pf/receipt.json"
    for index, name in enumerate(expected):
        entry = next(e for e in new["identity"]["cases"] if e["id"] == name)
        spec = json.loads((new_path / entry["public"] / "spec.json").read_text())
        observed, adapter = (
            f"c{index:02d}/observed.json",
            f"c{index:02d}/t/test-0001-owned/adapter-result.json",
        )
        save(pf.parent / observed, asdict(failed_run()))
        save(
            pf.parent / adapter,
            {
                "status": "failed",
                "pytest_exit_code": 1,
                "output_semantics": "validated_combined_pytest_log",
                "identity": {"environment_hash": ENVIRONMENT},
                "public_input_hash": spec["public_input_hash"],
            },
        )
        receipt["results"].append(
            {
                "case_id": name,
                "fingerprint": entry["fingerprint"],
                "spec_hash": entry["spec_hash"],
                "evidence_hash": entry["evidence_hash"],
                "public_input_hash": spec["public_input_hash"],
                "status": "matched",
                "observed": observed,
                "observed_hash": file_hash(pf.parent / observed),
                "adapter_result": adapter,
                "adapter_result_hash": file_hash(pf.parent / adapter),
            }
        )
    save(pf, receipt)
    yield {
        "checkpoint": cp_path,
        "dataset": dataset,
        "original_pack": old_path,
        "new_pack": new_path,
        "original_output": original,
        "recovery_descriptor": rd_path,
        "recovery_authorization": ra_path,
        "recovery_output": stage,
        "preflight": pf,
        "output": base / "r2",
    }
    mp.undo()


@pytest.fixture(scope="module")
def qualified_history(owned_history):
    return api().inspect_resume(*(owned_history[n] for n in api().PATH_FIELDS))


def test_inspect_binds_history_new_pack_and_complete_preflight(owned_history, qualified_history):
    descriptor = qualified_history
    assert len(descriptor["plan"]["slots"]) == 167
    assert descriptor["plan"]["previous_calls"] == 506
    assert descriptor["plan"]["cumulative_maximum_calls"] == 3613
    assert descriptor["evidence"]["preflight"]["case_count"] == 28
    assert len(descriptor["evidence"]["technical_events"]) == 2
    assert not owned_history["output"].exists()


def test_shared_worker_technical_stop_never_replays_and_report_keeps_saved_times(
    owned_history, qualified_history, monkeypatch
):
    module = api()
    descriptor = qualified_history

    def stopped(job, *, credential):
        raise RuntimeError("owned external worker failure")

    monkeypatch.setattr("benchmarks.evaluation.live_comparison.run_worker", stopped)
    result = module.execute_resume(
        descriptor, approval(descriptor["plan"]), credential_getter=lambda: "owned"
    )
    assert result["finished"] == 1
    assert result["rows"][0]["status"] == "technical_error"
    with pytest.raises(FileExistsError):
        module.execute_resume(
            descriptor, approval(descriptor["plan"]), credential_getter=no_credential
        )
    report = importlib.import_module("scripts.goldset50_adapter_report").report_resume(
        descriptor, owned_history["output"].parent / "combined"
    )
    assert report["planned"] == 300
    assert report["finished"] == 134
    assert report["usage"]["reserved_calls"] == report["usage"]["responses"] == 506
    assert len(report["technical_events"]) == 2
    assert report["goldset"]["complete"] is False
    assert len(report["timing_sources"]) == 2
    assert report["goldset"]["tasks"][0]["grading_seconds_known"] == 1
