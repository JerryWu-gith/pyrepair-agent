"""Explicit adapter-only third stage; saved stages are never replayed or rewritten."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation import goldset_jobs, goldset_live, goldset_pack, live_comparison
from benchmarks.evaluation.agent_input import PublicTaskSpec
from benchmarks.evaluation.cases import contained
from benchmarks.evaluation.comparison_evidence import FrozenParser
from benchmarks.evaluation.comparison_journal import _events
from benchmarks.evaluation.comparison_pack import _runtime, file_hash
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.experiment import digest
from benchmarks.evaluation.goldset_dataset import verify_dataset
from benchmarks.evaluation.live_plan import (
    SLOT_LIMITS,
    _overlaps,
    absolute_path,
    validate_authorization,
)
from pyrepair.models import PytestFailure, TestRun
from scripts import goldset50_recovery as recovery

ADAPTER = "benchmarks/evaluation/comparison_evidence.py"
PATH_FIELDS = (
    "checkpoint",
    "dataset",
    "original_pack",
    "new_pack",
    "original_output",
    "recovery_descriptor",
    "recovery_authorization",
    "recovery_output",
    "preflight",
    "output",
)


def adapter_sources():
    return {
        n: file_hash(ROOT / "scripts" / n)
        for n in ("goldset50_adapter_resume.py", "goldset50_adapter_report.py")
    }


def _source_files():
    files = [
        *sorted((ROOT / "src").rglob("*.py")),
        *sorted((ROOT / "benchmarks/evaluation").glob("*.py")),
        ROOT / "pyproject.toml",
        ROOT / "benchmarks/run_evaluation.py",
    ]
    return {p.relative_to(ROOT).as_posix(): file_hash(p) for p in files}


def _source_delta(checkpoint, current, runtime):
    previous = checkpoint["source_files"]
    old_runtime = checkpoint["runtime"]
    changed = {
        n: {"before": previous[n], "after": current[n]}
        for n in previous.keys() & current.keys()
        if previous[n] != current[n]
    }
    if (
        checkpoint["allowed_runtime_changes"] != [ADAPTER]
        or previous.keys() != current.keys()
        or set(changed) != {ADAPTER}
        or old_runtime["source_hash"] != digest(previous)
        or runtime["source_hash"] != digest(current)
        or digest({k: v for k, v in old_runtime.items() if k != "source_hash"})
        != digest({k: v for k, v in runtime.items() if k != "source_hash"})
    ):
        raise ValueError("unapproved source/runtime delta")
    return changed


def _suffix(slots, previous_calls):
    suffix = slots[133:]
    if (
        len(slots) != 300
        or len(suffix) != 167
        or previous_calls != 506
        or sum(s["method"] == "full-agent" for s in suffix) != 84
        or sum(s["method"] == "single-shot" for s in suffix) != 83
        or sum(SLOT_LIMITS[s["method"]] for s in suffix) != 3107
        or previous_calls + 3107 > 5550
    ):
        raise ValueError("adapter continuation schedule or cumulative budget changed")
    return suffix


def _preflight(receipt_path, pack_path, pack, expected):
    """Reparse the actual saved TestRun; receipt labels alone are not evidence."""
    receipt_path, pack_path = absolute_path(receipt_path), absolute_path(pack_path)
    receipt = read_json(receipt_path)
    header = {
        "version": 1,
        "kind": "public-baseline-preflight",
        "pack_path": str(pack_path),
        "pack_file_hash": file_hash(pack_path / "pack.json"),
        "pack_identity_hash": pack["identity_hash"],
        "runtime_hash": digest(pack["identity"]["runtime"]),
        "expected_cases": expected,
        "no_model_calls": True,
    }
    if (
        set(receipt) != {*header, "results"}
        or any(receipt.get(k) != v for k, v in header.items())
        or receipt["no_model_calls"] is not True
        or not isinstance(receipt["results"], list)
        or [r.get("case_id") for r in receipt["results"]] != expected
    ):
        raise ValueError("incomplete or changed public preflight receipt")
    hashes = {str(receipt_path): file_hash(receipt_path)}
    entries = {e["id"]: e for e in pack["identity"]["cases"]}
    for row in receipt["results"]:
        entry = entries[row["case_id"]]
        public = contained(pack_path, entry["public"])
        spec = PublicTaskSpec.from_dict(read_json(public / "spec.json"))
        identity = {
            "case_id": entry["id"],
            "fingerprint": entry["fingerprint"],
            "spec_hash": entry["spec_hash"],
            "evidence_hash": entry["evidence_hash"],
            "public_input_hash": spec.public_input_hash,
            "status": "matched",
        }
        if (
            set(row)
            != {*identity, "observed", "observed_hash", "adapter_result", "adapter_result_hash"}
            or any(row.get(k) != v for k, v in identity.items())
            or file_hash(public / "spec.json") != entry["spec_hash"]
            or file_hash(public / "evidence.json") != entry["evidence_hash"]
        ):
            raise ValueError("public preflight row identity changed")
        artifacts = {}
        for name in ("observed", "adapter_result"):
            path = contained(receipt_path.parent, row[name])
            sha = file_hash(path)
            if sha != row[name + "_hash"]:
                raise ValueError("public preflight artifact changed")
            hashes[str(path)] = sha
            artifacts[name] = read_json(path)
        raw = artifacts["observed"]
        run = TestRun(
            **{
                **raw,
                "command": tuple(raw["command"]),
                "failures": tuple(PytestFailure(**f) for f in raw["failures"]),
            }
        )
        adapter = artifacts["adapter_result"]
        if (
            type(run.exit_code) is not int
            or run.exit_code != 1
            or run.timed_out is not False
            or run.launch_error is not None
            or run.capture_source != "plugin"
            or any(f.phase == "collection" for f in run.failures)
            or not any(
                f.phase in {"call", "setup", "teardown"}
                and f.outcome == "failed"
                and f.node_id.partition("::")[0] in spec.visible_tests
                for f in run.failures
            )
            or adapter.get("status") != "failed"
            or adapter.get("pytest_exit_code") != 1
            or adapter.get("output_semantics") != "validated_combined_pytest_log"
            or adapter.get("identity", {}).get("environment_hash")
            != pack["identity"]["environment"]["verified_hash"]
            or adapter.get("public_input_hash") != spec.public_input_hash
        ):
            raise ValueError("public preflight is technical or not an executable baseline failure")
        FrozenParser(read_json(public / "evidence.json"), spec).parse(run)
    return {
        "path": str(receipt_path),
        "sha256": file_hash(receipt_path),
        "case_count": len(expected),
        "critical_hashes": hashes,
    }


def _zero_call_fault(record, calls):
    if (
        record.get("status") != "technical_error"
        or record.get("error_type") != "WorkerError"
        or record.get("candidate") is not None
        or record.get("grade") is not None
        or any(c["slot"] == record["slot"] for c in calls.values())
    ):
        raise ValueError("latest historical fault is not a zero-call WorkerError")


def _authority(output, authorization_path, plan):
    authorization = read_json(authorization_path)
    validate_authorization(authorization, plan)
    if read_json(output / "execution.json") != {
        "version": 1,
        "plan_hash": digest(plan),
        "authorization_hash": digest(authorization),
        "offline_owned_executor": False,
    }:
        raise ValueError("historical execution authority changed")
    return authorization


def _protected(paths, cases, plan):
    protected = [p for n, p in paths.items() if n != "output"]
    protected.append(paths["preflight"].parent)
    protected.extend(
        ROOT / n for n in ("src", "benchmarks", "scripts", "tests", ".git", ".agents", ".codex")
    )
    lock = absolute_path(plan["environment"]["lock_path"])
    protected.extend((lock, lock.with_name("environment-check.json")))
    protected.extend(p for c in cases for p in (c.buggy, c.private, c.description))
    if any(_overlaps(paths["output"], absolute_path(p)) for p in protected):
        raise ValueError("adapter output overlaps protected evidence or sources")
    roots = [
        paths[n]
        for n in ("dataset", "original_pack", "new_pack", "original_output", "recovery_output")
    ]
    if any(_overlaps(a, b) for i, a in enumerate(roots) for b in roots[i + 1 :]):
        raise ValueError("adapter source roots overlap")


def _historical(paths, old, checkpoint):
    """Historical identity is qualified from pinned raw bytes, never current verify_pack."""
    original, stage = paths["original_output"], paths["recovery_output"]
    prior = read_json(paths["recovery_descriptor"])
    cp = prior["checkpoint"]
    expected_paths = {
        "dataset": paths["dataset"],
        "pack": paths["original_pack"],
        "original_output": original,
        "output": stage,
    }
    if (
        prior.get("version") != 1
        or any(absolute_path(prior[n]) != p for n, p in expected_paths.items())
        or prior["plan"].get("recovery_sources") != checkpoint["recovery_sources"]
        or prior["plan"].get("checkpoint_hash") != digest(cp)
    ):
        raise ValueError("historical recovery descriptor changed")
    old_plan = goldset_live.describe_plan(paths["original_pack"], old, original, "formal", 5550)
    old_auth = _authority(original, absolute_path(prior["original_authorization"]), old_plan)
    if cp["original_plan_hash"] != digest(old_plan) or cp["original_authorization_hash"] != digest(
        old_auth
    ):
        raise ValueError("historical original authority changed")
    records = recovery._old_records(original, live_comparison._selected_pack(old, old_plan))
    original_calls = recovery._checked_calls(original / "q", old_plan["slots"][:130], 5550)
    original_tree = recovery.tree_identity(original)
    regrade = absolute_path(prior["regrade"])
    regrade_tree = recovery.tree_identity(regrade)
    candidate = recovery._candidate(read_json(original / "s0129/candidate.json"))
    grade = recovery._regrade(regrade, old, candidate)
    if (
        original_tree != cp["original_tree"]
        or regrade_tree != cp["regrade_tree"]
        or cp["calls"] != len(original_calls)
        or cp["responses"] != len(original_calls)
        or cp["terminal_records"] != 130
        or cp["normal_records"] != 129
        or cp["original_budget"] != 5550
        or cp["original_technical_error"] != records[-1]
        or cp["candidate_sha256"] != file_hash(original / "s0129/candidate.json")
        or cp["regrade_sha256"] != file_hash(regrade / "result.json")
        or cp["regrade_status"] != grade["status"]
    ):
        raise ValueError("historical original/regrade checkpoint changed")
    plan = goldset_live.describe_plan(paths["original_pack"], old, stage, "formal", 5550)
    plan.update(
        kind="pyrepair-goldset50-controlled-recovery",
        slots=plan["slots"][129:],
        call_limit=3145,
        maximum_slot_calls=3145,
        new_generation_slots=170,
        checkpoint_hash=digest(cp),
        original_plan_hash=digest(old_plan),
        original_budget=5550,
        previous_calls=len(original_calls),
        cumulative_maximum_calls=len(original_calls) + 3145,
        recovery_sources=recovery.recovery_sources(),
        reused_first_slot={
            "slot": recovery.FAILED_SLOT,
            "mode": "saved-candidate-and-validated-regrade",
            "new_model_calls": 0,
        },
    )
    if plan != prior["plan"]:
        raise ValueError("historical recovery plan changed")
    _authority(stage, paths["recovery_authorization"], plan)
    for root in (original, stage, regrade):
        recovery._no_locks(root)
        live_comparison._check_supervision(root)
    selected = live_comparison._selected_pack(old, plan)
    if read_json(stage / "run.json") != {"pack": selected["identity_hash"], "simulation": False}:
        raise ValueError("historical recovery run identity changed")
    histories = list(_events(stage, selected, False).values())
    if any(not h or h[-1]["event"] != "terminal" for h in histories[:5]) or any(histories[5:]):
        raise ValueError("historical recovery must have exactly five terminal records")
    recovered = [h[-1]["data"] for h in histories[:5]]
    if any(r["status"] == "technical_error" for r in recovered[:4]) or [
        r["slot"] for r in records[:129] + recovered[:4]
    ] != [s["slot"] for s in old["identity"]["slots"][:133]]:
        raise ValueError("historical normal prefix is not exactly 133 slots")
    calls = recovery._checked_calls(stage / "q", plan["slots"][1:5], 3145)
    _zero_call_fault(recovered[-1], calls)
    fault = stage / "s0004"
    supervision = read_json(fault / "supervision.json")
    if (
        supervision.get("returncode") != 2
        or supervision.get("status") != "worker_error"
        or any((fault / n).exists() for n in ("candidate.json", "grade.json"))
        or len(original_calls) + len(calls) != 506
    ):
        raise ValueError("historical latest worker fault or answered calls changed")
    trees = {
        "original": original_tree,
        "recovery": recovery.tree_identity(stage),
        "regrade": regrade_tree,
    }
    critical = {
        str(paths["recovery_descriptor"]): file_hash(paths["recovery_descriptor"]),
        str(paths["recovery_authorization"]): file_hash(paths["recovery_authorization"]),
        str(absolute_path(prior["original_authorization"])): file_hash(
            absolute_path(prior["original_authorization"])
        ),
    }
    for tree in trees.values():
        for rel, sha in tree["files"].items():
            if (
                "/" not in rel
                or rel in {"q/budget.json", "q/calls.jsonl"}
                or rel.endswith(
                    ("/candidate.json", "/grade.json", "/job.json", "/supervision.json")
                )
            ):
                critical[str(Path(tree["path"]) / rel)] = sha
    return {
        "trees": trees,
        "critical_hashes": critical,
        "technical_events": [records[-1], recovered[-1]],
        "previous_calls": 506,
    }, records[:129] + recovered[:4]


def inspect_resume(
    checkpoint,
    dataset,
    original_pack,
    new_pack,
    original_output,
    recovery_descriptor,
    recovery_authorization,
    recovery_output,
    preflight,
    output,
):
    """Qualify exactly 133 saved ordinary slots and describe 167 fresh generation slots."""
    paths = {
        n: absolute_path(v)
        for n, v in zip(
            PATH_FIELDS,
            (
                checkpoint,
                dataset,
                original_pack,
                new_pack,
                original_output,
                recovery_descriptor,
                recovery_authorization,
                recovery_output,
                preflight,
                output,
            ),
            strict=True,
        )
    }
    cp = read_json(paths["checkpoint"])
    if (
        cp.get("version") != 1
        or len(cp["source_files"]) != 80
        or any(
            cp[n] != expected
            for n, expected in {
                "previous_calls": 506,
                "planned_normal_prefix": 133,
                "planned_suffix": 167,
                "new_call_maximum": 3107,
                "original_call_limit": 5550,
            }.items()
        )
    ):
        raise ValueError("invalid prechange checkpoint")
    change = _source_delta(cp, _source_files(), _runtime())
    if cp["recovery_sources"] != recovery.recovery_sources():
        raise ValueError("historical recovery controller source changed")
    for name, expected in cp["cli_files"].items():
        if file_hash(ROOT / "benchmarks" / name) != expected:
            raise ValueError("historical CLI changed")
    for name, expected in cp["artifacts"].items():
        if file_hash(absolute_path(name)) != expected:
            raise ValueError("prechange checkpoint artifact changed")
    old = read_json(paths["original_pack"] / "pack.json")
    if (
        set(old) != {"identity", "identity_hash"}
        or digest(old["identity"]) != old["identity_hash"]
        or old["identity"]["runtime"] != cp["runtime"]
    ):
        raise ValueError("historical raw pack/runtime identity changed")
    cases = verify_dataset(paths["dataset"])
    new = goldset_pack.verify_goldset_pack(paths["new_pack"], cases)
    if {k: v for k, v in old["identity"].items() if k != "runtime"} != {
        k: v for k, v in new["identity"].items() if k != "runtime"
    } or any(
        recovery.tree_identity(paths["original_pack"] / n)["files"]
        != recovery.tree_identity(paths["new_pack"] / n)["files"]
        for n in ("p", "control")
    ):
        raise ValueError("new pack changes more than adapter runtime")
    plan = goldset_live.describe_plan(paths["new_pack"], new, paths["output"], "formal", 5550)
    _protected(paths, cases, plan)
    evidence, _records = _historical(paths, old, cp)
    suffix = _suffix(plan["slots"], evidence["previous_calls"])
    selected = {s["case_id"] for s in suffix}
    expected = [e["id"] for e in new["identity"]["cases"] if e["id"] in selected]
    if len(expected) != 28:
        raise ValueError("adapter preflight must cover exactly 28 remaining public baselines")
    evidence["preflight"] = _preflight(paths["preflight"], paths["new_pack"], new, expected)
    evidence.update(
        checkpoint_sha256=file_hash(paths["checkpoint"]),
        source_change=change,
        original_runtime=old["identity"]["runtime"],
        new_runtime=new["identity"]["runtime"],
        original_pack_hash=old["identity_hash"],
        new_pack_hash=new["identity_hash"],
    )
    evidence["critical_hashes"].update(evidence["preflight"]["critical_hashes"])
    evidence["critical_hashes"].update(
        {str(absolute_path(p)): h for p, h in cp["artifacts"].items()}
    )
    evidence["critical_hashes"][str(paths["checkpoint"])] = file_hash(paths["checkpoint"])
    evidence["critical_hashes"][str(paths["new_pack"] / "pack.json")] = file_hash(
        paths["new_pack"] / "pack.json"
    )
    plan.update(
        kind="pyrepair-goldset50-adapter-fixed-resume",
        slots=suffix,
        call_limit=3107,
        maximum_slot_calls=3107,
        new_generation_slots=167,
        retained_normal_slots=133,
        previous_calls=506,
        original_budget=5550,
        cumulative_maximum_calls=3613,
        checkpoint_hash=digest(evidence),
        adapter_sources=adapter_sources(),
    )
    return {
        "version": 1,
        **{n: str(p) for n, p in paths.items()},
        "evidence": evidence,
        "plan": plan,
    }


def validate_descriptor(descriptor):
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"version", *PATH_FIELDS, "evidence", "plan"}
        or descriptor["version"] != 1
        or descriptor["plan"]["adapter_sources"] != adapter_sources()
        or descriptor["plan"]["checkpoint_hash"] != digest(descriptor["evidence"])
    ):
        raise ValueError("adapter descriptor/source identity changed")
    actual = inspect_resume(*(descriptor[n] for n in PATH_FIELDS))
    if actual != descriptor:
        raise ValueError("adapter descriptor/source evidence changed")
    return actual


def _check_critical(descriptor):
    if adapter_sources() != descriptor["plan"]["adapter_sources"]:
        raise ValueError("adapter controller source changed")
    cp = read_json(Path(descriptor["checkpoint"]))
    _source_delta(cp, _source_files(), _runtime())
    for name, expected in descriptor["evidence"]["critical_hashes"].items():
        if file_hash(absolute_path(name)) != expected:
            raise ValueError("critical adapter source changed")
    for tree in descriptor["evidence"]["trees"].values():
        recovery._no_locks(Path(tree["path"]))
        live_comparison._check_supervision(Path(tree["path"]))


def execute_resume(descriptor, authorization, *, credential_getter=None):
    validate_authorization(authorization, descriptor["plan"])
    validate_descriptor(descriptor)
    if absolute_path(descriptor["output"]).exists():
        raise FileExistsError("adapter stage already exists; automatic resume/replay is forbidden")
    cases = verify_dataset(Path(descriptor["dataset"]))
    frozen = goldset_pack.verify_goldset_pack(Path(descriptor["new_pack"]), cases)
    _check_critical(descriptor)

    def verifier(path, selected_cases):
        _check_critical(descriptor)
        return goldset_pack.verify_goldset_pack(path, selected_cases)

    def describer(path, pack, output, mode, call_limit):
        _check_critical(descriptor)
        if (
            str(absolute_path(path)) != descriptor["new_pack"]
            or pack != frozen
            or str(absolute_path(output)) != descriptor["output"]
            or mode != "formal"
            or call_limit != 3107
        ):
            raise ValueError("adapter execution hook identity changed")
        return descriptor["plan"]

    if credential_getter is None:
        from benchmarks.run_goldset50 import _configured_credential

        credential_getter = _configured_credential
    return live_comparison.execute_comparison(
        descriptor["new_pack"],
        cases,
        descriptor["output"],
        "formal",
        3107,
        authorization,
        resume=False,
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
            result = inspect_resume(*(getattr(args, n) for n in PATH_FIELDS))
        elif args.action == "execute":
            descriptor = read_json(args.descriptor)
            if any(
                _overlaps(absolute_path(descriptor["output"]), absolute_path(p))
                for p in (args.descriptor, args.authorization)
            ):
                raise ValueError("adapter output overlaps descriptor or approval")
            result = execute_resume(descriptor, read_json(args.authorization))
        else:
            from scripts.goldset50_adapter_report import report_resume

            result = report_resume(read_json(args.descriptor), args.output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 2 if any(r["status"] == "technical_error" for r in result.get("rows", [])) else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Adapter continuation refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
