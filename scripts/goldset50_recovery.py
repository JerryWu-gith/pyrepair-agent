"""Explicit, separately authorized recovery; never rewrites the stopped run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation import goldset_jobs, goldset_live, goldset_pack, live_comparison
from benchmarks.evaluation.comparison_budget import (
    CallBudget,
    _calls,
    append_event,
    checked_path,
    write_new,
)
from benchmarks.evaluation.comparison_journal import TECHNICAL, _candidate, _events
from benchmarks.evaluation.comparison_pack import file_hash
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.experiment import digest
from benchmarks.evaluation.goldset_dataset import verify_dataset
from benchmarks.evaluation.layered_grading import validate_layered_grade
from benchmarks.evaluation.live_plan import (
    SLOT_LIMITS,
    _overlaps,
    absolute_path,
    validate_authorization,
)

FAILED_SLOT = "os_boltons_addlist_458--2--full-agent"
PATH_FIELDS = ("dataset", "pack", "original_output", "original_authorization", "regrade", "output")


def recovery_sources():
    return {
        name: file_hash(ROOT / "scripts" / name)
        for name in ("goldset50_recovery.py", "goldset50_recovery_report.py")
    }


def tree_identity(root):
    """Raw bytes, including logs; links and special files are not evidence."""
    root = absolute_path(root)
    files = {}
    for path in sorted(root.rglob("*")):
        checked_path(path)
        if path.is_file():
            files[path.relative_to(root).as_posix()] = file_hash(path)
        elif not path.is_dir():
            raise ValueError("nonordinary recovery evidence")
    if not files:
        raise ValueError("empty recovery evidence tree")
    return {"path": str(root), "files": files, "hash": digest(files)}


def _no_locks(root):
    if any(root.rglob("writer.lock")):
        raise ValueError("unresolved writer lock in recovery evidence")


def _old_records(root, selected):
    if read_json(root / "run.json") != {"pack": selected["identity_hash"], "simulation": False}:
        raise ValueError("original run identity changed")
    states = _events(root, selected, False)
    histories = list(states.values())
    if any(not h or h[-1]["event"] != "terminal" for h in histories[:130]) or any(histories[130:]):
        raise ValueError("original checkpoint must be exactly 130 terminal records")
    records = [h[-1]["data"] for h in histories[:130]]
    if (
        any(r["status"] == "technical_error" for r in records[:129])
        or records[-1]["slot"] != FAILED_SLOT
        or records[-1]["status"] != "technical_error"
        or records[-1]["grade"]["status"] != "environment_error"
        or records[-1]["candidate"]["status"] != "candidate"
        or records[-1]["error_type"] is not None
    ):
        raise ValueError("unexpected original technical checkpoint")
    return records


def _checked_calls(root, slots, limit):
    config, calls = _calls(root)
    if config != {"version": 1, "limit": limit}:
        raise ValueError("original budget identity changed")
    by_id = {s["slot"]: s for s in slots}
    for call in calls.values():
        slot = by_id.get(call["slot"])
        if (
            slot is None
            or call["slot_limit"] != SLOT_LIMITS[slot["method"]]
            or (call["role"] == "single-shot") != (slot["method"] == "single-shot")
            or call.get("result", {}).get("event") != "response"
        ):
            raise ValueError("unresolved or unbound original model call")
    return calls


def _regrade(root, pack, candidate):
    slot = pack["identity"]["slots"][129]
    entry = next(e for e in pack["identity"]["cases"] if e["id"] == slot["case_id"])
    value = validate_layered_grade(
        read_json(root / "result.json"),
        root,
        candidate_patch=candidate["patch"],
        frozen_case=entry,
    )
    if value["status"] in {*TECHNICAL, "simulated"} or value["extended"]["status"] in {
        *TECHNICAL,
        "interrupted",
    }:
        raise ValueError("saved regrade is technical or simulated")
    core = read_json(root / "core-grade.json")
    extended = read_json(root / "extended-regression.json")
    for stage in (core.get("visible"), core.get("hidden"), extended.get("stage")):
        if stage is not None and (
            not isinstance(stage, dict)
            or stage.get("backend") != "docker"
            or stage.get("started") is not True
            or stage.get("cleanup_errors") != []
            or stage.get("status") not in {"passed", "failed"}
            or stage.get("identity", {}).get("environment_hash")
            != pack["identity"]["environment"]["verified_hash"]
        ):
            raise ValueError("regrade stage differs from the verified environment")
    return value


def _protected(paths, cases, plan):
    protected = [paths[n] for n in PATH_FIELDS if n != "output"]
    protected.extend(
        ROOT / n for n in ("src", "benchmarks", "scripts", "tests", ".git", ".agents", ".codex")
    )
    lock = absolute_path(plan["environment"]["lock_path"])
    protected.extend((lock, lock.with_name("environment-check.json")))
    protected.extend(p for c in cases for p in (c.buggy, c.private, c.description))
    if any(_overlaps(paths["output"], absolute_path(p)) for p in protected):
        raise ValueError("recovery output overlaps protected sources")
    sources = [paths[n] for n in ("dataset", "pack", "original_output", "regrade")]
    if any(_overlaps(a, b) for index, a in enumerate(sources) for b in sources[index + 1 :]):
        raise ValueError("recovery source trees overlap")


def inspect_recovery(dataset, pack, original_output, original_authorization, regrade, output):
    """Qualify saved evidence and describe exactly 171 slots, without key access."""
    paths = {
        n: absolute_path(v)
        for n, v in zip(
            PATH_FIELDS,
            (dataset, pack, original_output, original_authorization, regrade, output),
            strict=True,
        )
    }
    if any(_overlaps(paths["output"], paths[n]) for n in PATH_FIELDS if n != "output"):
        raise ValueError("recovery output overlaps protected evidence")
    cases = verify_dataset(paths["dataset"])
    frozen = goldset_pack.verify_goldset_pack(paths["pack"], cases)
    old_plan = goldset_live.describe_plan(
        paths["pack"], frozen, paths["original_output"], "formal", 5550
    )
    old_auth = read_json(paths["original_authorization"])
    validate_authorization(old_auth, old_plan)
    if read_json(paths["original_output"] / "execution.json") != {
        "version": 1,
        "plan_hash": digest(old_plan),
        "authorization_hash": digest(old_auth),
        "offline_owned_executor": False,
    }:
        raise ValueError("original execution identity changed")
    _protected(paths, cases, old_plan)
    _no_locks(paths["original_output"])
    _no_locks(paths["regrade"])
    live_comparison._check_supervision(paths["original_output"])
    records = _old_records(
        paths["original_output"], live_comparison._selected_pack(frozen, old_plan)
    )
    calls = _checked_calls(paths["original_output"] / "q", old_plan["slots"][:130], 5550)
    candidate = _candidate(read_json(paths["original_output"] / "s0129/candidate.json"))
    grade = _regrade(paths["regrade"], frozen, candidate)
    # One expensive complete snapshot per inspection; only critical hashes per worker.
    old_tree, regrade_tree = (
        tree_identity(paths["original_output"]),
        tree_identity(paths["regrade"]),
    )
    critical = {
        str(paths["original_output"] / rel): sha
        for rel, sha in old_tree["files"].items()
        if rel in {"execution.json", "run.json", "journal.jsonl", "q/budget.json", "q/calls.jsonl"}
        or rel.endswith(("/candidate.json", "/grade.json", "/supervision.json", "/job.json"))
    }
    critical.update(
        {
            str(paths["regrade"] / rel): sha
            for rel, sha in regrade_tree["files"].items()
            if "/" not in rel
        }
    )
    critical[str(paths["original_authorization"])] = file_hash(paths["original_authorization"])
    checkpoint = {
        "terminal_records": len(records),
        "normal_records": 129,
        "calls": len(calls),
        "responses": len(calls),
        "original_budget": 5550,
        "original_plan_hash": digest(old_plan),
        "original_authorization_hash": digest(old_auth),
        "original_tree": old_tree,
        "regrade_tree": regrade_tree,
        "candidate_sha256": file_hash(paths["original_output"] / "s0129/candidate.json"),
        "regrade_sha256": file_hash(paths["regrade"] / "result.json"),
        "regrade_status": grade["status"],
        "original_technical_error": records[-1],
        "critical_hashes": critical,
    }
    plan = goldset_live.describe_plan(paths["pack"], frozen, paths["output"], "formal", 5550)
    suffix = plan["slots"][129:]
    maximum = sum(SLOT_LIMITS[s["method"]] for s in suffix[1:])
    if (
        len(suffix) != 171
        or suffix[0]["slot"] != FAILED_SLOT
        or maximum != 3145
        or len(calls) + maximum > 5550
    ):
        raise ValueError("recovery schedule or cumulative maximum changed")
    plan.update(
        kind="pyrepair-goldset50-controlled-recovery",
        slots=suffix,
        call_limit=3145,
        maximum_slot_calls=3145,
        new_generation_slots=170,
        checkpoint_hash=digest(checkpoint),
        original_plan_hash=digest(old_plan),
        original_budget=5550,
        previous_calls=len(calls),
        cumulative_maximum_calls=len(calls) + 3145,
        recovery_sources=recovery_sources(),
        reused_first_slot={
            "slot": FAILED_SLOT,
            "mode": "saved-candidate-and-validated-regrade",
            "new_model_calls": 0,
        },
    )
    return {
        "version": 1,
        **{n: str(p) for n, p in paths.items()},
        "checkpoint": checkpoint,
        "plan": plan,
    }


def validate_descriptor(descriptor):
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"version", *PATH_FIELDS, "checkpoint", "plan"}
        or descriptor["version"] != 1
    ):
        raise ValueError("invalid recovery descriptor")
    checkpoint = descriptor["checkpoint"]
    if (
        descriptor["plan"]["checkpoint_hash"] != digest(checkpoint)
        or any(
            checkpoint[n]["hash"] != digest(checkpoint[n]["files"])
            for n in ("original_tree", "regrade_tree")
        )
        or descriptor["plan"]["recovery_sources"] != recovery_sources()
    ):
        raise ValueError("recovery descriptor/source identity changed")
    actual = inspect_recovery(*(descriptor[n] for n in PATH_FIELDS))
    if actual != descriptor:
        raise ValueError("recovery descriptor/source identity changed")
    return actual


def _check_critical(descriptor):
    if recovery_sources() != descriptor["plan"]["recovery_sources"]:
        raise ValueError("recovery controller source changed")
    for name, expected in descriptor["checkpoint"]["critical_hashes"].items():
        if file_hash(Path(name)) != expected:
            raise ValueError("critical recovery source changed")
    _no_locks(Path(descriptor["original_output"]))
    _no_locks(Path(descriptor["regrade"]))


def _same_json(path, value):
    try:
        write_new(path, value)
    except FileExistsError:
        if read_json(path) != value:
            raise ValueError("existing recovery bootstrap artifact differs") from None


def _copy_new(source, target):
    data = checked_path(source).read_bytes()
    target = checked_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if target.read_bytes() != data:
            raise ValueError("existing recovery copy differs") from None


def _bootstrap(descriptor, authorization, frozen):
    output = absolute_path(descriptor["output"])
    identity = {
        "version": 1,
        "plan_hash": digest(descriptor["plan"]),
        "authorization_hash": digest(authorization),
        "offline_owned_executor": False,
    }
    provenance = {
        "version": 1,
        "checkpoint_hash": descriptor["plan"]["checkpoint_hash"],
        "source_candidate": str(Path(descriptor["original_output"]) / "s0129/candidate.json"),
        "source_regrade": descriptor["regrade"],
        "new_model_calls": 0,
        "candidate_sha256": descriptor["checkpoint"]["candidate_sha256"],
        "regrade_sha256": descriptor["checkpoint"]["regrade_sha256"],
    }
    if output.exists() and not (output / "execution.json").is_file():
        raise ValueError("existing output lacks recovery execution identity")
    output.mkdir(parents=True, exist_ok=True)
    _same_json(output / "execution.json", identity)
    _no_locks(output)
    _same_json(output / "bootstrap.json", provenance)
    CallBudget(output / "q", 3145)
    selected = live_comparison._selected_pack(frozen, descriptor["plan"])
    _same_json(output / "run.json", {"pack": selected["identity_hash"], "simulation": False})
    _copy_new(Path(provenance["source_candidate"]), output / "s0000/candidate.json")
    source = Path(descriptor["regrade"])
    for rel in descriptor["checkpoint"]["regrade_tree"]["files"]:
        _copy_new(source / rel, output / "s0000/g" / rel)
    _copy_new(source / "result.json", output / "s0000/grade.json")
    # Saved grade, not a fake executor/worker/API response. Resume adds the terminal.
    states = _events(output, selected, False)
    history = states[FAILED_SLOT]
    expected = [
        ("started", None),
        ("candidate", file_hash(output / "s0000/candidate.json")),
        ("grade", file_hash(output / "s0000/grade.json")),
    ]
    for index, (kind, data) in enumerate(expected):
        event = {
            "pack": selected["identity_hash"],
            "slot": FAILED_SLOT,
            "event": kind,
            "data": data,
        }
        if index < len(history):
            if history[index] != event:
                raise ValueError("changed recovery bootstrap journal")
        else:
            append_event(output / "journal.jsonl", event)
    return output


def execute_recovery(descriptor, authorization, *, credential_getter=None):
    """Only a newly approved stage may execute; normal credentials stay deferred."""
    validate_authorization(authorization, descriptor["plan"])
    validate_descriptor(descriptor)
    cases = verify_dataset(Path(descriptor["dataset"]))
    frozen = goldset_pack.verify_goldset_pack(Path(descriptor["pack"]), cases)
    _check_critical(descriptor)
    _bootstrap(descriptor, authorization, frozen)

    def verifier(path, selected_cases):
        _check_critical(descriptor)
        return goldset_pack.verify_goldset_pack(path, selected_cases)

    def describer(path, pack, output, mode, call_limit):
        _check_critical(descriptor)
        if (
            str(absolute_path(path)) != descriptor["pack"]
            or pack != frozen
            or str(absolute_path(output)) != descriptor["output"]
            or mode != "formal"
            or call_limit != 3145
        ):
            raise ValueError("recovery controller hook identity changed")
        return descriptor["plan"]

    if credential_getter is None:
        from benchmarks.run_goldset50 import _configured_credential

        credential_getter = _configured_credential
    return live_comparison.execute_comparison(
        descriptor["pack"],
        cases,
        descriptor["output"],
        "formal",
        3145,
        authorization,
        resume=True,
        credential_getter=credential_getter,
        pack_verifier=verifier,
        plan_describer=describer,
        job_builder=goldset_jobs.public_job,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    inspect_parser = commands.add_parser("inspect")
    for field in PATH_FIELDS:
        inspect_parser.add_argument("--" + field.replace("_", "-"), type=Path, required=True)
    for name in ("execute", "report"):
        command = commands.add_parser(name)
        command.add_argument("--descriptor", type=Path, required=True)
        command.add_argument(
            "--authorization" if name == "execute" else "--output", type=Path, required=True
        )
    args = parser.parse_args(argv)
    try:
        if args.action == "inspect":
            result = inspect_recovery(*(getattr(args, n) for n in PATH_FIELDS))
        elif args.action == "execute":
            result = execute_recovery(read_json(args.descriptor), read_json(args.authorization))
        else:
            from scripts.goldset50_recovery_report import report_recovery

            result = report_recovery(read_json(args.descriptor), args.output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Recovery refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
