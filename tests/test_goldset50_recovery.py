"""Controlled recovery uses only owned files and external-boundary doubles."""

import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from benchmarks.evaluation import comparison_pack, goldset_live, goldset_pack
from benchmarks.evaluation.cases import case_fingerprint
from benchmarks.evaluation.comparison_budget import CallBudget, append_event, write_new
from benchmarks.evaluation.comparison_journal import _record
from benchmarks.evaluation.comparison_pack import file_hash
from benchmarks.evaluation.experiment import digest
from benchmarks.evaluation.goldset_dataset import assemble_dataset, verify_dataset
from benchmarks.evaluation.layered_grading import _aggregate, _save_phase
from benchmarks.evaluation.live_comparison import _selected_pack
from tests.test_catalog_calibration import ENVIRONMENT, owned_report
from tests.test_comparison_evidence import OwnedRunner
from tests.test_goldset50_dataset import materialized_selection
from tests.test_live_comparison import no_credential
from tests.test_live_plan import approval


def api():
    assert importlib.util.find_spec("scripts.goldset50_recovery") is not None, (
        "controlled goldset recovery missing"
    )
    return importlib.import_module("scripts.goldset50_recovery")


def test_controlled_recovery_is_available():
    api()


def saved_grade(folder, entry, patch, status="passed"):
    identity = {
        "case": entry["fingerprint"],
        "patch": __import__("hashlib").sha256(patch.encode()).hexdigest(),
        "regression": digest(None),
        "collection": digest(None),
    }
    write_new(folder / "identity.json", identity)
    core = {"case_id": entry["id"], "status": status}
    if status == "passed":
        core.update(
            {
                phase: {
                    "backend": "docker",
                    "started": True,
                    "cleanup_errors": [],
                    "identity": {"environment_hash": ENVIRONMENT},
                    "status": "passed",
                    "outcomes": dict.fromkeys(entry["core_collection"][phase], "passed"),
                }
                for phase in ("visible", "hidden")
            }
        )
    extended = {"status": "not_applicable", "stage": None}
    _save_phase(folder, "core-grade.json", core)
    _save_phase(folder, "extended-regression.json", extended)
    grade = _aggregate(
        core,
        extended,
        {
            name: file_hash(folder / name)
            for name in ("core-grade.json", "extended-regression.json")
        },
        identity,
    )
    write_new(folder / "result.json", grade)
    return grade


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    """One file-only fixed schedule; no 300-slot model simulation."""
    base = tmp_path_factory.mktemp("owned")
    mp = pytest.MonkeyPatch()
    mp.setattr(
        "benchmarks.evaluation.docker_runner.DockerTestRunner.assert_environment_verified",
        lambda self: {"environment_hash": ENVIRONMENT, "image_id": "owned-image"},
    )
    mp.setattr(comparison_pack, "DockerAgentTestRunner", lambda *a: OwnedRunner())
    dataset = base / "dataset"
    assemble_dataset([materialized_selection(base / "materialized")], dataset)
    cases = verify_dataset(dataset)
    _, _, template = owned_report(base / "template")
    calibration = base / "calibrations"
    for case in cases:
        record = {
            **copy.deepcopy(template),
            "case_id": case.id,
            "fingerprint": case_fingerprint(case),
        }
        write_new(calibration / case.id / "validation.json", record)
    lock = base / "environment-lock.json"
    write_new(lock, {"image_id": "owned-image"})
    write_new(lock.with_name("environment-check.json"), {})
    pack_path = base / "pack"
    goldset_pack.prepare_goldset_pack(dataset, pack_path, lock, [calibration])
    pack = goldset_pack.verify_goldset_pack(pack_path, cases)
    original = base / "original"
    plan = goldset_live.describe_plan(pack_path, pack, original, "formal", 5550)
    auth = approval(plan)
    auth_path = base / "original-approval.json"
    write_new(auth_path, auth)
    write_new(
        original / "execution.json",
        {
            "version": 1,
            "plan_hash": digest(plan),
            "authorization_hash": digest(auth),
            "offline_owned_executor": False,
        },
    )
    selected = _selected_pack(pack, plan)
    write_new(original / "run.json", {"pack": selected["identity_hash"], "simulation": False})
    quota = CallBudget(original / "q", 5550)
    for index, slot in enumerate(plan["slots"][:130]):
        folder = original / f"s{index:04d}"
        candidate = {
            "status": "candidate",
            "patch": "owned patch",
            "internal_success": True,
            "duration_seconds": 1.25,
        }
        write_new(folder / "candidate.json", candidate)
        entry = next(e for e in pack["identity"]["cases"] if e["id"] == slot["case_id"])
        grade = saved_grade(
            folder / "g",
            entry,
            candidate["patch"],
            "environment_error" if index == 129 else "passed",
        )
        write_new(folder / "grade.json", grade)
        write_new(folder / "g/grading-time.json", {"duration_seconds": 0.5})
        for kind, data in (
            ("started", None),
            ("candidate", file_hash(folder / "candidate.json")),
            ("grade", file_hash(folder / "grade.json")),
            ("terminal", _record(slot, candidate, grade, False)),
        ):
            append_event(
                original / "journal.jsonl",
                {
                    "pack": selected["identity_hash"],
                    "slot": slot["slot"],
                    "event": kind,
                    "data": data,
                },
            )
        number = quota.reserve(
            slot["slot"],
            "repair" if slot["method"] == "full-agent" else "single-shot",
            36 if slot["method"] == "full-agent" else 1,
        )
        quota.finish(
            {"event": "response", "call_id": number, "prompt_tokens": 10, "completion_tokens": 2}
        )
    failed = plan["slots"][129]
    regrade = base / "regrade"
    saved_grade(
        regrade,
        next(e for e in pack["identity"]["cases"] if e["id"] == failed["case_id"]),
        "owned patch",
    )
    write_new(regrade / "grading-time.json", {"duration_seconds": 0.75})
    yield {
        "base": base,
        "dataset": dataset,
        "pack": pack_path,
        "original_output": original,
        "original_authorization": auth_path,
        "regrade": regrade,
        "cases": cases,
        "frozen": pack,
    }
    mp.undo()


def inspect(evidence, output):
    return api().inspect_recovery(
        *(
            evidence[n]
            for n in ("dataset", "pack", "original_output", "original_authorization", "regrade")
        ),
        output,
    )


def test_exact_recovery_suffix_budget_and_frozen_checkpoint(evidence, tmp_path):
    result = inspect(evidence, tmp_path / "stage")
    plan, checkpoint = result["plan"], result["checkpoint"]
    assert len(plan["slots"]) == 171
    assert plan["slots"][0]["slot"] == "os_boltons_addlist_458--2--full-agent"
    assert plan["slots"] == evidence["frozen"]["identity"]["slots"][129:]
    assert plan["new_generation_slots"] == 170
    assert plan["maximum_slot_calls"] == plan["call_limit"] == 3145
    assert plan["reused_first_slot"]["new_model_calls"] == 0
    assert checkpoint["terminal_records"] == 130
    assert checkpoint["normal_records"] == 129
    assert checkpoint["calls"] == checkpoint["responses"] == 130
    assert set(plan["recovery_sources"]) == {
        "goldset50_recovery.py",
        "goldset50_recovery_report.py",
    }
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("mutation", ["approval", "source", "oldtree", "regrade"])
def test_changed_binding_rejected_before_key_and_output(evidence, tmp_path, mutation):
    descriptor = inspect(evidence, tmp_path / "stage")
    value = approval(descriptor["plan"])
    if mutation == "approval":
        value["approved"] = False
    elif mutation == "source":
        descriptor["plan"]["recovery_sources"]["goldset50_recovery.py"] = "0" * 64
        value = approval(descriptor["plan"])
    else:
        descriptor["checkpoint"]["original_tree" if mutation == "oldtree" else "regrade_tree"][
            "hash"
        ] = "0" * 64
        descriptor["plan"]["checkpoint_hash"] = digest(descriptor["checkpoint"])
        value = approval(descriptor["plan"])
    with pytest.raises(ValueError):
        api().execute_recovery(descriptor, value, credential_getter=no_credential)
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize(
    "target", ["dataset", "pack", "original_output", "regrade", "original_authorization"]
)
def test_output_overlap_rejected(evidence, target):
    with pytest.raises(ValueError, match="overlap"):
        inspect(evidence, evidence[target] / "nested")


def test_bootstrap_replay_zero_calls_then_technical_stop_and_resume(
    evidence, tmp_path, monkeypatch
):
    recovery = api()
    descriptor = inspect(evidence, tmp_path / "stage")

    # External worker is the only changed execution boundary.
    def stopped(job, *, credential):
        raise RuntimeError("owned external worker stop")

    monkeypatch.setattr("benchmarks.evaluation.live_comparison.run_worker", stopped)
    summary = recovery.execute_recovery(
        descriptor, approval(descriptor["plan"]), credential_getter=lambda: "owned-not-a-key"
    )
    assert summary["finished"] == 2
    assert [r["status"] for r in summary["rows"][:3]] == ["core_passed", "technical_error", "unrun"]
    stage = Path(descriptor["output"])
    assert not (stage / "s0000/job.json").exists()
    assert not (stage / "s0000/supervision.json").exists()
    assert not (stage / "s0000/responses").exists()
    assert json.loads((stage / "bootstrap.json").read_text())["new_model_calls"] == 0
    assert json.loads((stage / "q/budget.json").read_text())["limit"] == 3145
    assert summary["usage"]["reserved_calls"] == 0
    journal = (stage / "journal.jsonl").read_bytes()
    again = recovery.execute_recovery(
        descriptor, approval(descriptor["plan"]), credential_getter=no_credential
    )
    assert again == summary
    assert (stage / "journal.jsonl").read_bytes() == journal
    report = importlib.import_module("scripts.goldset50_recovery_report").report_recovery(
        descriptor, tmp_path / "combined"
    )
    assert report["kind"].startswith("STAGED")
    assert report["planned"] == 300
    assert report["finished"] == 131
    assert report["usage"]["reserved_calls"] == 130
    assert report["original_technical_error"]["status"] == "technical_error"
    assert all(g["success_rate"] is None for g in report["goldset"]["groups"] if g["unrun"])
    assert json.loads((tmp_path / "combined/s0129/g/grading-time.json").read_text()) == {
        "duration_seconds": 0.75
    }
    assert report["timing_sources"]["s0129/g/grading-time.json"]["sha256"] == file_hash(
        evidence["regrade"] / "grading-time.json"
    )
    with pytest.raises(FileExistsError):
        importlib.import_module("scripts.goldset50_recovery_report").report_recovery(
            descriptor, tmp_path / "combined"
        )
