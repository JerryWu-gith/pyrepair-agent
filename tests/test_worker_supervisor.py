"""Only the owned process tree and identity-checked recorded CIDs may be stopped."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.evaluation.comparison_budget import write_new
from tests.test_comparison_worker import owned_job
from tests.test_docker_runner import CID
from tests.test_docker_runner import (
    setup_backend as setup_backend,  # noqa: PLC0414 - fixture re-export
)


def recorded_stage(tmp_path, lock):
    stage = tmp_path / "owned/t/test-0001/p.log.docker"
    (stage / "input/repo").mkdir(parents=True)
    (stage / "output").mkdir()
    (stage / "container.cid").write_text(CID, encoding="ascii")
    import hashlib

    request = {
        "version": 2,
        "run_id": "1" * 32,
        "stage_id": "2" * 32,
        "input_hash": "a" * 64,
        "environment_hash": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "paths": ["test_owned.py"],
        "required": [],
        "timeout": 120,
        "mode": "agent",
        "target": None,
    }
    write_new(stage / "input/request.json", request)
    return stage, request


@pytest.mark.parametrize("mutation", ["name", "image", "profile", "mount", "lock"])
def test_wrong_container_identity_is_not_stopped_or_removed(
    setup_backend, tmp_path, monkeypatch, mutation
):
    from benchmarks.evaluation import worker_supervisor as supervisor

    module, _, lock, _, _ = setup_backend
    stage, request = recorded_stage(tmp_path, lock)
    inspected = {
        "Id": CID,
        "Name": "/pyrepair-" + request["run_id"],
        "State": {"Running": True},
        "Config": {"Image": "owned"},
    }
    if mutation == "name":
        inspected["Name"] = "/another-user-container"
    elif mutation == "image":
        inspected["Config"]["Image"] = "changed"
    elif mutation == "lock":
        request["environment_hash"] = "b" * 64
        (stage / "input/request.json").write_text(json.dumps(request), encoding="utf-8")

    actions = []
    original_cli = module._cli

    def cli(arguments, **kwargs):
        if arguments[0] not in {"container", "stop", "rm"}:
            return original_cli(arguments, **kwargs)
        actions.append(arguments)
        return CID + "\n"

    monkeypatch.setattr(module, "_cli", cli)
    monkeypatch.setattr(module, "_inspect", lambda *args, **kwargs: copy.deepcopy(inspected))

    def profile(value, verified_lock, mounts):
        if mutation in {"image", "profile", "mount"}:
            raise ValueError("owned identity mismatch")

    monkeypatch.setattr(module, "_inspect_profile", profile)
    result = supervisor.cleanup_owned(tmp_path / "owned", lock)
    assert result["status"] == "environment_error"
    assert not any(a[0] in {"stop", "rm"} for a in actions)


def test_only_exact_recorded_cid_is_cleaned_and_verified_stopped(
    setup_backend, tmp_path, monkeypatch
):
    from benchmarks.evaluation import worker_supervisor as supervisor

    module, _, lock, _, _ = setup_backend
    stage, request = recorded_stage(tmp_path, lock)
    alive = True
    actions = []
    original_cli = module._cli

    def cli(arguments, **kwargs):
        nonlocal alive
        if arguments[0] not in {"container", "stop", "rm"}:
            return original_cli(arguments, **kwargs)
        actions.append(arguments)
        if arguments[0] == "stop":
            alive = False
        return CID + "\n" if arguments[0] == "container" else ""

    def inspect(cid, host, timeout=30):
        assert cid == CID
        return {"Id": CID, "Name": "/pyrepair-" + request["run_id"], "State": {"Running": alive}}

    def profile(value, locked, mounts):
        assert mounts == {"/input": stage / "input", "/output": stage / "output"}

    monkeypatch.setattr(module, "_cli", cli)
    monkeypatch.setattr(module, "_inspect", inspect)
    monkeypatch.setattr(module, "_inspect_profile", profile)
    result = supervisor.cleanup_owned(tmp_path / "owned", lock)
    assert result["status"] == "clean"
    assert result["removed"] == [CID]
    assert actions == [
        ["container", "ls", "--all", "--no-trunc", "--filter=id=" + CID, "--format={{.ID}}"],
        ["stop", "--time=5", CID],
        ["rm", CID],
    ]


def test_already_removed_cid_needs_no_destructive_action(setup_backend, tmp_path, monkeypatch):
    from benchmarks.evaluation import worker_supervisor as supervisor

    module, _, lock, _, _ = setup_backend
    recorded_stage(tmp_path, lock)
    actions = []
    original_cli = module._cli

    def cli(arguments, **kwargs):
        if arguments[0] not in {"container", "stop", "rm"}:
            return original_cli(arguments, **kwargs)
        actions.append(arguments)
        return ""

    monkeypatch.setattr(module, "_cli", cli)
    assert supervisor.cleanup_owned(tmp_path / "owned", lock)["status"] == "clean"
    assert len(actions) == 1
    assert actions[0][0] == "container"


def test_partial_create_without_recorded_cid_is_unknown_not_claimed_clean(setup_backend, tmp_path):
    from benchmarks.evaluation.worker_supervisor import cleanup_owned

    _, _, lock, _, _ = setup_backend
    stage, _ = recorded_stage(tmp_path, lock)
    (stage / "container.cid").unlink()
    result = cleanup_owned(tmp_path / "owned", lock)
    assert result["status"] == "environment_error"
    assert result["removed"] == []


def test_parent_kills_owned_worker_timeout_and_never_restarts(tmp_path, monkeypatch):
    from benchmarks.evaluation.worker_supervisor import run_worker

    job = owned_job(tmp_path, monkeypatch)
    script = tmp_path / "owned-worker.py"
    script.write_text(
        "import pathlib,sys,time\n"
        "p=pathlib.Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True)\n"
        "(p/'owned-started').write_text('one')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    command = [sys.executable, str(script), job["output"]]
    with pytest.raises(subprocess.TimeoutExpired):
        run_worker(job, worker_command=command, timeout=1)
    assert Path(job["output"]).joinpath("owned-started").read_text() == "one"
    assert (
        json.loads(Path(job["output"]).joinpath("supervision.json").read_text("utf-8"))["status"]
        == "timeout"
    )
    with pytest.raises(FileExistsError):
        run_worker(job, worker_command=command, timeout=1)


def test_nonzero_worker_keeps_response_but_does_not_accept_candidate(tmp_path, monkeypatch):
    from benchmarks.evaluation.worker_supervisor import WorkerError, run_worker

    job = owned_job(tmp_path, monkeypatch)
    script = tmp_path / "owned-crash.py"
    script.write_text("raise SystemExit(2)\n", encoding="utf-8")
    with pytest.raises(WorkerError):
        run_worker(job, worker_command=[sys.executable, str(script)])
    result = json.loads(Path(job["output"]).joinpath("supervision.json").read_text("utf-8"))
    assert result["status"] == "worker_error"
    assert result["returncode"] == 2
    assert result["cleanup"]["status"] == "clean"


def test_cleanup_failure_is_technical_even_when_worker_exits_zero(tmp_path, monkeypatch):
    from benchmarks.evaluation import worker_supervisor as supervisor

    job = owned_job(tmp_path, monkeypatch)
    monkeypatch.setattr(supervisor, "cleanup_owned", lambda *args: {"status": "environment_error"})
    with pytest.raises(supervisor.WorkerError):
        supervisor.run_worker(job, worker_command=[sys.executable, "-c", "pass"])
    value = json.loads(Path(job["output"]).joinpath("supervision.json").read_text("utf-8"))
    assert value["status"] == "cleanup_error"


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_candidate_then_abnormal_exit_remains_a_replayable_paused_terminal(
    tmp_path, monkeypatch, cleanup_fails
):
    from benchmarks.evaluation import worker_supervisor as supervisor
    from benchmarks.evaluation.comparison_journal import run_slots
    from tests.test_comparison_journal import owned_pack

    job = owned_job(tmp_path, monkeypatch)
    pack = owned_pack()
    script = tmp_path / "owned-candidate-crash.py"
    script.write_text(
        "import json,pathlib,sys\n"
        "p=pathlib.Path(sys.argv[1])/'candidate.json'\n"
        "p.write_text(json.dumps({'status':'no_patch','patch':'','internal_success':None,'duration_seconds':0.1}))\n"
        f"raise SystemExit({0 if cleanup_fails else 2})\n",
        encoding="utf-8",
    )
    if cleanup_fails:
        monkeypatch.setattr(
            supervisor, "cleanup_owned", lambda *args: {"status": "environment_error"}
        )

    def executor(slot, folder):
        job["output"] = str(folder.absolute())
        return supervisor.run_worker(job, worker_command=[sys.executable, str(script), str(folder)])

    def forbidden(*args):
        pytest.fail("technical candidate must not be graded or re-executed")

    output = tmp_path / "run"
    records = run_slots(pack, output, executor, forbidden)
    assert records[0]["status"] == "technical_error"
    assert (output / "s0000/candidate.json").is_file()
    before = (output / "journal.jsonl").read_bytes()
    assert run_slots(pack, output, forbidden, forbidden) == records
    assert (output / "journal.jsonl").read_bytes() == before
