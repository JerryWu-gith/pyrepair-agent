"""Bounded suffix execution; an explicit second stage, never a disguised resume."""

from __future__ import annotations

from pathlib import Path

from .cases import contained
from .comparison_budget import CallBudget, read_usage, write_new
from .comparison_journal import run_slots
from .comparison_pack import file_hash
from .comparison_reporting import summarize_comparison
from .container_protocol import read_json
from .continuation_assets import original_records, verify_continuation_assets
from .docker_runner import DockerTestRunner
from .experiment import digest
from .layered_grading import grade_layered
from .live_comparison import _check_supervision, _credential, _selected_pack
from .live_plan import absolute_path, describe_plan, public_job, validate_authorization
from .worker_supervisor import WorkerError, run_worker


def inspect_continuation(pack_path, cases, output, call_limit=1221):
    pack_path, output = absolute_path(pack_path), absolute_path(output)
    pack, value = verify_continuation_assets(pack_path, cases, check_original=True)
    if type(call_limit) is not int or not 1 <= call_limit <= 1221:
        raise ValueError("continuation request limit must be 1..1221")
    plan = describe_plan(pack_path, pack, output, "formal", call_limit)
    if any(
        output.is_relative_to(absolute_path(value["checkpoint"][n]))
        or absolute_path(value["checkpoint"][n]).is_relative_to(output)
        for n in ("pack", "original_output")
    ):
        raise ValueError("continuation output overlaps original evidence")
    protected = [p.resolve() for c in cases for p in (c.buggy, c.private, c.description)]
    protected.append(Path(plan["environment"]["lock_path"]).resolve())
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError("continuation output overlaps protected inputs")
    plan.update(
        kind="pyrepair-adapter-fixed-continuation",
        slots=pack["identity"]["slots"][54:],
        maximum_slot_calls=1221,
        continuation_hash=file_hash(pack_path / "continuation.json"),
        original_checkpoint_hash=value["checkpoint_hash"],
    )
    return plan


def _add_usage(first, second):
    result = {**second, "roles": {}}
    for name in ("reserved_calls", "responses"):
        result[name] = first[name] + second[name]
    for role in first["roles"]:
        a, b = first["roles"][role], second["roles"][role]
        result["roles"][role] = {
            key: None if a.get(key) is None or b.get(key) is None else a[key] + b[key]
            for key in (
                "calls",
                "prompt_tokens",
                "completion_tokens",
                "known_prompt_tokens",
                "known_completion_tokens",
            )
        }
    result["usage_known"] = first["usage_known"] and second["usage_known"]
    return result


def _offline(summary):
    summary.update(
        kind="OFFLINE staged integration - NOT model performance",
        real_model_trials=0,
        performance_measured=False,
    )
    for group in summary["groups"]:
        group["core_accepted"] = group["core_acceptance_rate"] = None
    for pair in summary["paired_cases"]:
        pair["agent_minus_single_accepted"], pair["comparable_trials"] = None, 0
        for trial in pair["trials"]:
            trial["delta"] = None


def execute_continuation(
    pack_path,
    cases,
    output,
    authorization,
    *,
    call_limit=1221,
    resume=False,
    offline_executor=None,
    credential_getter=None,
):
    plan = inspect_continuation(pack_path, cases, output, call_limit)
    validate_authorization(authorization, plan)
    pack_path, output = absolute_path(pack_path), absolute_path(output)
    pack, descriptor = verify_continuation_assets(pack_path, cases, check_original=True)
    if (
        pack["identity_hash"] != plan["pack_hash"]
        or file_hash(pack_path / "continuation.json") != plan["continuation_hash"]
    ):
        raise ValueError("continuation changed after authorization")
    identity = {
        "version": 1,
        "plan_hash": digest(plan),
        "authorization_hash": digest(authorization),
        "offline_owned_executor": offline_executor is not None,
    }
    if resume:
        if (
            read_json(output / "execution.json") != identity
            or not (output / "q/budget.json").is_file()
            or (output / "writer.lock").exists()
        ):
            raise WorkerError("continuation recovery identity/ownership is unresolved")
        _check_supervision(output)
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_new(output / "execution.json", identity)
    CallBudget(output / "q", call_limit)
    selected = _selected_pack(pack, plan)
    runner = DockerTestRunner(Path(plan["environment"]["lock_path"]))
    by_id = {c.id: c for c in cases}

    def executor(slot, folder):
        current, _ = verify_continuation_assets(pack_path, cases)
        if (
            digest(current) != digest(pack)
            or file_hash(pack_path / "continuation.json") != plan["continuation_hash"]
        ):
            raise ValueError("continuation changed before worker")
        job = public_job(pack_path, pack, slot, folder, output / "q", call_limit)
        if offline_executor is not None:
            return offline_executor(job)
        key = (credential_getter or _credential)()
        return run_worker(job, credential=key)

    def grader(slot, candidate, folder):
        entry = next(e for e in pack["identity"]["cases"] if e["id"] == slot["case_id"])
        public = contained(pack_path, entry["public"])
        nodes = read_json(pack_path / "control" / public.name / "collection.json")
        return grade_layered(
            by_id[slot["case_id"]],
            candidate["patch"],
            folder,
            test_runner=runner,
            expected_nodes=nodes["expected_nodes"],
        )

    records = run_slots(selected, output, executor, grader)
    usage = read_usage(output / "q")
    summary = summarize_comparison(selected, records, usage=usage, execution_mode="formal")
    summary.update(
        kind="Adapter-fixed continuation - 66-slot stage",
        execution_mode="continuation",
        execution_plan_hash=digest(plan),
        frozen_pack_hash=pack["identity_hash"],
        performance_measured=offline_executor is None,
    )
    checkpoint = descriptor["checkpoint"]
    old_pack, previous = original_records(checkpoint, check_tree=True)
    combined = summarize_comparison(
        pack,
        previous[:54] + records,
        usage=_add_usage(read_usage(absolute_path(checkpoint["original_output"]) / "q"), usage),
        execution_mode="formal",
    )
    combined.update(
        kind="STAGED comparison - evaluation adapter fixed between stages",
        performance_measured=offline_executor is None,
        provenance={
            "retained_normal_slots": 54,
            "original_technical_events": 1,
            "original_error_slot": previous[54]["slot"],
            "original_output": checkpoint["original_output"],
            "new_output": str(output),
            "original_pack": old_pack["identity_hash"],
            "new_pack": pack["identity_hash"],
            "original_runtime": old_pack["identity"]["runtime"],
            "new_runtime": pack["identity"]["runtime"],
            "continuation_plan_hash": digest(plan),
            "smoke_included": False,
        },
    )
    if offline_executor is not None:
        _offline(summary)
        _offline(combined)
    from benchmarks.run_comparison import _save_report

    _save_report(output, summary)
    _save_report(output / "combined", combined)
    return summary
