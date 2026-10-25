"""Owned data exercises the continuation contract, never provider or Docker."""

import copy
import hashlib
import json

import pytest


def test_source_gate_rejects_an_agent_change_but_allows_only_the_comparator(tmp_path):
    from benchmarks.evaluation.continuation_assets import source_files, verify_source_change
    from benchmarks.evaluation.experiment import digest

    files = {
        "src/pyrepair/repair_agent.py": "original agent",
        "benchmarks/evaluation/comparison_evidence.py": "original comparison",
        "pyproject.toml": "[project]",
        "benchmarks/run_evaluation.py": "original cli",
        "benchmarks/run_comparison.py": "original comparison cli",
        "benchmarks/run_live_comparison.py": "original live cli",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    before = source_files(tmp_path)
    checkpoint = {"source_files": before}
    (tmp_path / "benchmarks/evaluation/comparison_evidence.py").write_text("fixed")
    result = verify_source_change(checkpoint, tmp_path)
    assert result["changed"] == ["benchmarks/evaluation/comparison_evidence.py"]
    assert result["source_hash"] == digest(source_files(tmp_path))
    (tmp_path / "src/pyrepair/repair_agent.py").write_text("tuned agent")
    with pytest.raises(ValueError, match="source"):
        verify_source_change(checkpoint, tmp_path)


def owned_stopped_run(tmp_path, monkeypatch):
    from benchmarks.evaluation import comparison_pack as pack_module
    from benchmarks.evaluation.comparison_budget import CallBudget, write_new
    from benchmarks.evaluation.comparison_journal import run_slots
    from benchmarks.evaluation.comparison_reporting import summarize_comparison
    from benchmarks.evaluation.continuation_assets import source_files, tree_hash
    from benchmarks.evaluation.experiment import digest, runtime_identity
    from benchmarks.evaluation.live_comparison import _selected_pack
    from benchmarks.evaluation.live_plan import describe_plan
    from benchmarks.evaluation.worker_supervisor import WorkerError
    from tests.test_live_comparison import live_fixture
    from tests.test_live_plan import approval

    path, cases = live_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(pack_module, "runtime_identity", runtime_identity)
    pack = json.loads((path / "pack.json").read_text("utf-8"))
    pack["identity"]["runtime"] = pack_module._runtime()
    pack["identity_hash"] = digest(pack["identity"])
    (path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    pack = json.loads((path / "pack.json").read_text("utf-8"))
    old = tmp_path / "old"
    plan = describe_plan(path, pack, old, "formal", 2220)
    authority = approval(plan)
    authorization_path = tmp_path / "old-authorization.json"
    write_new(authorization_path, authority)
    old.mkdir()
    write_new(
        old / "execution.json",
        {
            "version": 1,
            "plan_hash": digest(plan),
            "authorization_hash": digest(authority),
            "offline_owned_executor": False,
        },
    )
    CallBudget(old / "q", 2220)
    selected = _selected_pack(pack, plan)
    called = []

    def executor(slot, folder):
        called.append(slot["slot"])
        if len(called) == 55:
            write_new(folder / "job.json", {"slot": slot})
            write_new(
                folder / "supervision.json",
                {
                    "job_hash": digest({"slot": slot}),
                    "status": "worker_error",
                    "returncode": 2,
                    "cleanup": {"status": "clean", "errors": [], "absent": []},
                },
            )
            raise WorkerError("owned zero-call baseline error")
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    from benchmarks.evaluation.layered_grading import grade_layered

    by_id = {c.id: c for c in cases}
    records = run_slots(
        selected, old, executor, lambda s, c, f: grade_layered(by_id[s["case_id"]], c["patch"], f)
    )
    monkeypatch.setattr(
        "benchmarks.evaluation.docker_runner.DockerTestRunner.assert_environment_verified",
        lambda self: {"environment_hash": "owned-hash", "image_id": "owned-image"},
    )
    from benchmarks.evaluation.comparison_budget import read_usage
    from benchmarks.run_comparison import _save_report

    _save_report(old, summarize_comparison(selected, records, usage=read_usage(old / "q")))
    checkpoint = {
        "version": 1,
        "pack": str(path),
        "original_output": str(old),
        "original_authorization": str(authorization_path),
        "runtime": pack["identity"]["runtime"],
        "source_files": source_files(),
        "original_artifacts_hash": tree_hash(old),
        "original_artifacts_count": sum(p.is_file() for p in old.rglob("*")),
        "pack_file_hash": hashlib.sha256((path / "pack.json").read_bytes()).hexdigest(),
        "approval": "Owned offline fixture; not performance",
    }
    checkpoint_path = tmp_path / "checkpoint.json"
    write_new(checkpoint_path, checkpoint)
    return checkpoint_path, cases, old


def test_prepare_and_inspect_only_suffix_preserve_original_artifacts(tmp_path, monkeypatch):
    from benchmarks.evaluation.comparison_continuation import inspect_continuation
    from benchmarks.evaluation.continuation_assets import prepare_continuation, tree_hash

    cp, cases, old = owned_stopped_run(tmp_path, monkeypatch)
    original = tree_hash(old)
    pack = prepare_continuation(cp, cases, tmp_path / "newpack")
    plan = inspect_continuation(pack, cases, tmp_path / "suffix")
    assert len(plan["slots"]) == 66
    assert plan["slots"][0]["slot"] == "case_09--1--full-agent"
    assert plan["maximum_slot_calls"] == plan["call_limit"] == 1221
    assert not (tmp_path / "suffix").exists()
    assert tree_hash(old) == original


@pytest.mark.parametrize("drift", ["artifact", "fault_call", "missing_error"])
def test_original_evidence_drift_is_rejected_before_copy(tmp_path, monkeypatch, drift):
    from benchmarks.evaluation.continuation_assets import prepare_continuation, tree_hash

    cp, cases, old = owned_stopped_run(tmp_path, monkeypatch)
    if drift == "artifact":
        (old / "s0000/candidate.json").write_text("{}")
    elif drift == "fault_call":
        from benchmarks.evaluation.comparison_budget import CallBudget

        CallBudget(old / "q", 2220).reserve("case_09--1--full-agent", "repair", 36)
    else:
        lines = (old / "journal.jsonl").read_text("utf-8").splitlines()
        (old / "journal.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    # Exercise the semantic checks as well as the outer immutable-tree digest.
    checkpoint = json.loads(cp.read_text("utf-8"))
    checkpoint["original_artifacts_hash"] = tree_hash(old)
    cp.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_continuation(cp, cases, tmp_path / "newpack")
    assert not (tmp_path / "newpack").exists()


def test_continuation_executes_66_once_and_invalid_approval_never_reads_key(tmp_path, monkeypatch):
    from benchmarks.evaluation.comparison_continuation import (
        execute_continuation,
        inspect_continuation,
    )
    from benchmarks.evaluation.continuation_assets import prepare_continuation, tree_hash
    from tests.test_live_plan import approval

    cp, cases, old = owned_stopped_run(tmp_path, monkeypatch)
    before = tree_hash(old)
    pack = prepare_continuation(cp, cases, tmp_path / "newpack")
    output = tmp_path / "suffix"
    plan = inspect_continuation(pack, cases, output)
    called = []

    def no_key():
        pytest.fail("owned or invalid execution must not read key")

    def executor(job):
        called.append(job["slot"]["slot"])
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    bad = copy.deepcopy(plan)
    bad["slots"].reverse()
    with pytest.raises(ValueError):
        execute_continuation(
            pack, cases, output, approval(bad), offline_executor=executor, credential_getter=no_key
        )
    assert not output.exists()
    result = execute_continuation(
        pack, cases, output, approval(plan), offline_executor=executor, credential_getter=no_key
    )
    assert called == [s["slot"] for s in plan["slots"]]
    assert result["planned"] == result["finished"] == 66
    combined = json.loads((output / "combined/summary.json").read_text("utf-8"))
    assert combined["planned"] == combined["finished"] == 120
    assert combined["provenance"]["retained_normal_slots"] == 54
    assert combined["provenance"]["original_technical_events"] == 1
    assert all(g["core_acceptance_rate"] is None for g in combined["groups"])
    saved = (output / "journal.jsonl").read_bytes()
    execute_continuation(
        pack,
        cases,
        output,
        approval(plan),
        resume=True,
        offline_executor=lambda job: pytest.fail("do not resend"),
        credential_getter=no_key,
    )
    assert (output / "journal.jsonl").read_bytes() == saved
    assert tree_hash(old) == before


def test_new_technical_error_stops_and_resume_does_not_resend_or_grow_budget(tmp_path, monkeypatch):
    from benchmarks.evaluation.comparison_continuation import (
        execute_continuation,
        inspect_continuation,
    )
    from benchmarks.evaluation.continuation_assets import prepare_continuation
    from tests.test_live_plan import approval

    cp, cases, _old = owned_stopped_run(tmp_path, monkeypatch)
    pack = prepare_continuation(cp, cases, tmp_path / "newpack")
    output = tmp_path / "suffix"
    with pytest.raises(ValueError, match="limit"):
        inspect_continuation(pack, cases, output, 1222)
    plan = inspect_continuation(pack, cases, output)
    called = []

    def executor(job):
        called.append(job["slot"]["slot"])
        if len(called) == 2:
            raise RuntimeError("owned infrastructure failure")
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    result = execute_continuation(pack, cases, output, approval(plan), offline_executor=executor)
    assert result["finished"] == 2 and result["unrun"] == 64
    assert sum(g["technical_errors"] for g in result["groups"]) == 1
    again = execute_continuation(
        pack,
        cases,
        output,
        approval(plan),
        resume=True,
        offline_executor=lambda job: pytest.fail("technical terminal must not be refilled"),
        credential_getter=lambda: pytest.fail("no model access during recovery"),
    )
    assert again == result
    assert len(called) == 2
