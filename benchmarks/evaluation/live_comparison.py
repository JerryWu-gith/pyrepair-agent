"""Trusted execution controller. Approval and all identities precede key access."""

from __future__ import annotations

import copy
import os
from pathlib import Path

from .cases import contained
from .comparison_budget import CallBudget, read_usage, write_new
from .comparison_journal import run_slots
from .comparison_pack import verify_pack
from .comparison_reporting import summarize_comparison
from .container_protocol import read_json
from .docker_runner import DockerTestRunner
from .experiment import digest
from .layered_grading import grade_layered
from .live_plan import absolute_path, describe_plan, public_job, validate_authorization
from .worker_supervisor import WorkerError, run_worker


def inspect_execution(pack_path, cases, output, mode, call_limit):
    pack = verify_pack(absolute_path(pack_path), cases)
    plan = describe_plan(pack_path, pack, output, mode, call_limit)
    destination = absolute_path(output)
    sources = [Path(plan["environment"]["lock_path"])]
    for case in cases:
        sources.extend((case.buggy, case.private, case.description))
    if any(
        destination.is_relative_to(p.resolve()) or p.resolve().is_relative_to(destination)
        for p in sources
    ):
        raise ValueError("execution output overlaps protected evaluation assets")
    return plan


def _selected_pack(pack, plan):
    identity = copy.deepcopy(pack["identity"])
    identity["slots"] = plan["slots"]
    selected = {s["case_id"] for s in plan["slots"]}
    identity["cases"] = [e for e in identity["cases"] if e["id"] in selected]
    identity["execution_plan_hash"] = digest(plan)
    return {"identity": identity, "identity_hash": digest(identity)}


def _credential():
    value = os.environ.get("DEEPSEEK_API_KEY", "")
    if not value.strip():
        raise ValueError("missing credential; no probe request is permitted")
    return value


def _check_supervision(output):
    """Unknown worker liveness cannot be resolved by silently spawning another."""
    for job_path in output.glob("s[0-9][0-9][0-9][0-9]/job.json"):
        folder = absolute_path(job_path.parent)
        job = read_json(absolute_path(job_path))
        supervision = read_json(folder / "supervision.json")
        if (
            supervision.get("job_hash") != digest(job)
            or supervision.get("cleanup", {}).get("status") != "clean"
        ):
            raise WorkerError("prior worker termination/cleanup is not confirmed")


def execute_comparison(
    pack_path,
    cases,
    output,
    mode,
    call_limit,
    authorization,
    *,
    resume=False,
    offline_executor=None,
    credential_getter=None,
):
    plan = inspect_execution(pack_path, cases, output, mode, call_limit)
    validate_authorization(authorization, plan)
    pack = verify_pack(absolute_path(pack_path), cases)
    if pack["identity_hash"] != plan["pack_hash"]:
        raise ValueError("frozen pack no longer matches execution authorization")
    output = absolute_path(output)
    identity = {
        "version": 1,
        "plan_hash": digest(plan),
        "authorization_hash": digest(authorization),
        "offline_owned_executor": offline_executor is not None,
    }
    if resume:
        if read_json(output / "execution.json") != identity:
            raise ValueError("execution identity changed; offline and live cannot share results")
        if not (output / "q/budget.json").is_file():
            raise ValueError("missing original shared budget; refusing to create another")
        if (output / "writer.lock").exists():
            raise WorkerError("writer ownership is unresolved; no automatic stale-lock removal")
        _check_supervision(output)
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_new(output / "execution.json", identity)
    quota = output / "q"
    CallBudget(quota, call_limit)
    selected = _selected_pack(pack, plan)
    by_id = {c.id: c for c in cases}
    runner = DockerTestRunner(Path(plan["environment"]["lock_path"]))

    def executor(slot, folder):
        if digest(verify_pack(absolute_path(pack_path), cases)) != digest(pack):
            raise ValueError("frozen comparison changed before worker execution")
        job = public_job(pack_path, pack, slot, folder, quota, call_limit)
        if offline_executor is not None:
            return offline_executor(job)
        key = (credential_getter or _credential)()  # Only new authorized slots need a key.
        return run_worker(job, credential=key)

    def grader(slot, candidate, folder):
        entry = next(e for e in pack["identity"]["cases"] if e["id"] == slot["case_id"])
        public = contained(absolute_path(pack_path), entry["public"])
        nodes = read_json(absolute_path(pack_path) / "control" / public.name / "collection.json")
        return grade_layered(
            by_id[slot["case_id"]],
            candidate["patch"],
            folder,
            test_runner=runner,
            expected_nodes=nodes["expected_nodes"],
        )

    records = run_slots(selected, output, executor, grader)
    summary = summarize_comparison(selected, records, usage=read_usage(quota), execution_mode=mode)
    summary.update(
        frozen_pack_hash=pack["identity_hash"],
        execution_plan_hash=digest(plan),
        execution_mode=mode,
        performance_measured=offline_executor is None,
    )
    if offline_executor is not None:
        summary.update(
            kind="OFFLINE OWNED INTEGRATION - NOT model performance", real_model_trials=0
        )
        for group in summary["groups"]:
            group["core_accepted"] = group["core_acceptance_rate"] = None
        for row in summary["paired_cases"]:
            row["agent_minus_single_accepted"] = None
            row["comparable_trials"] = 0
            for trial in row["trials"]:
                trial["delta"] = None
    from benchmarks.run_comparison import _save_report

    _save_report(output, summary)
    return summary
