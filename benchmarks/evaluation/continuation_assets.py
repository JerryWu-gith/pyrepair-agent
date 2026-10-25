"""Explicit adapter-only rebase: retain old evidence, never relax verify_pack."""

from __future__ import annotations

import copy
import shutil

from .comparison_budget import _calls, checked_path, write_new
from .comparison_journal import _events
from .comparison_pack import _runtime, file_hash, verify_pack
from .container_protocol import read_json
from .experiment import ROOT, digest
from .live_comparison import _check_supervision, _selected_pack
from .live_plan import absolute_path, describe_plan, validate_authorization

CHANGED = {"benchmarks/evaluation/comparison_evidence.py"}
ADDED = {
    "benchmarks/evaluation/continuation_assets.py",
    "benchmarks/evaluation/comparison_continuation.py",
    "benchmarks/run_continuation.py",
}
CLIS = {
    "benchmarks/run_comparison.py",
    "benchmarks/run_live_comparison.py",
    "benchmarks/run_continuation.py",
}


def source_files(root=ROOT):
    root = absolute_path(root)
    files = [
        *sorted((root / "src").rglob("*.py")),
        *sorted((root / "benchmarks/evaluation").glob("*.py")),
        root / "pyproject.toml",
        root / "benchmarks/run_evaluation.py",
        *(root / name for name in sorted(CLIS) if (root / name).is_file()),
    ]
    return {p.relative_to(root).as_posix(): file_hash(p) for p in files}


def tree_hash(root):
    root = absolute_path(root)
    return digest(
        {
            p.relative_to(root).as_posix(): file_hash(p)
            for p in sorted(root.rglob("*"))
            if checked_path(p).is_file()
        }
    )


def verify_source_change(checkpoint, root=ROOT):
    before, after = checkpoint["source_files"], source_files(root)
    changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    if not set(changed) <= CHANGED or not set(added) <= ADDED or removed:
        raise ValueError("continuation source change exceeds the approved adapter-only scope")
    return {"changed": changed, "added": added, "source_hash": digest(after)}


def original_records(checkpoint, *, check_tree=False):
    """Read/validate old results in place; a technical terminal is never rewritten."""
    path = absolute_path(checkpoint["pack"])
    output = absolute_path(checkpoint["original_output"])
    if file_hash(path / "pack.json") != checkpoint["pack_file_hash"]:
        raise ValueError("original frozen pack changed")
    if check_tree and tree_hash(output) != checkpoint["original_artifacts_hash"]:
        raise ValueError("original run artifacts changed")
    old = read_json(path / "pack.json")
    if digest(old["identity"]) != old["identity_hash"]:
        raise ValueError("invalid original pack")
    if old["identity"]["runtime"] != checkpoint["runtime"]:
        raise ValueError("original runtime does not match checkpoint")
    authority = read_json(absolute_path(checkpoint["original_authorization"]))
    plan = describe_plan(path, old, output, "formal", 2220)
    validate_authorization(authority, plan)
    if read_json(output / "execution.json") != {
        "version": 1,
        "plan_hash": digest(plan),
        "authorization_hash": digest(authority),
        "offline_owned_executor": False,
    }:
        raise ValueError("original live execution identity changed")
    if (output / "writer.lock").exists() or (output / "q/writer.lock").exists():
        raise ValueError("original writer ownership is unresolved")
    _check_supervision(output)
    histories = _events(output, _selected_pack(old, plan), False)
    records = []
    for slot in plan["slots"]:
        history = histories[slot["slot"]]
        if history and history[-1]["event"] == "terminal":
            records.append(history[-1]["data"])
        elif history:
            raise ValueError("unfinished original slot")
    if (
        len(records) != 55
        or any(r["status"] not in {"core_passed", "failed"} for r in records[:54])
        or records[-1]["status"] != "technical_error"
        or records[-1]["error_type"] != "WorkerError"
        or records[-1]["candidate"] is not None
        or records[-1]["grade"] is not None
    ):
        raise ValueError("continuation requires the exact 54-normal/one-zero-call-error prefix")
    config, calls = _calls(output / "q")
    allowed = {r["slot"] for r in records[:54]}
    if config != {"version": 1, "limit": 2220} or any(
        c["slot"] not in allowed or c.get("result", {}).get("event") != "response"
        for c in calls.values()
    ):
        raise ValueError("fault slot may have spent a model call or old calls are unresolved")
    fault = read_json(output / "s0054/supervision.json")
    if fault["status"] != "worker_error" or fault["returncode"] != 2:
        raise ValueError("original zero-call worker error was not confirmed")
    return old, records


def _checkpoint_runtime(checkpoint):
    before = checkpoint["source_files"]
    runtime = checkpoint["runtime"]
    if digest({k: v for k, v in before.items() if k not in CLIS}) != runtime["source_hash"]:
        raise ValueError("checkpoint source manifest does not reconstruct original runtime")
    for name, key in (
        ("run_comparison.py", "comparison_cli_hash"),
        ("run_live_comparison.py", "live_comparison_cli_hash"),
    ):
        if before["benchmarks/" + name] != runtime[key]:
            raise ValueError("checkpoint CLI identity changed")
    current = _runtime()
    if digest({k: v for k, v in current.items() if k != "source_hash"}) != digest(
        {k: v for k, v in runtime.items() if k != "source_hash"}
    ):
        raise ValueError("continuation dependencies/platform/CLI changed")


def prepare_continuation(checkpoint_path, cases, output):
    checkpoint = read_json(absolute_path(checkpoint_path))
    _checkpoint_runtime(checkpoint)
    delta = verify_source_change(checkpoint)
    old, _ = original_records(checkpoint, check_tree=True)
    output = absolute_path(output)
    protected = [absolute_path(checkpoint[n]) for n in ("pack", "original_output")]
    protected += [p.resolve() for c in cases for p in (c.buggy, c.private, c.description)]
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError("continuation pack overlaps protected assets")
    output.mkdir(parents=True, exist_ok=False)
    source = absolute_path(checkpoint["pack"])
    for name in ("p", "control"):
        shutil.copytree(source / name, output / name)
    new = copy.deepcopy(old)
    new["identity"]["runtime"] = _runtime()
    new["identity_hash"] = digest(new["identity"])
    write_new(output / "pack.json", new)
    verify_pack(output, cases)  # Same verifier and unchanged old assets/calibration.
    write_new(
        output / "continuation.json",
        {
            "version": 1,
            "checkpoint": checkpoint,
            "checkpoint_hash": digest(checkpoint),
            "source_delta": delta,
            "current_source_files": source_files(),
            "new_pack_hash": new["identity_hash"],
            "calibration_reused": True,
            "prefix_slots": 54,
            "suffix_slots": 66,
        },
    )
    if (
        tree_hash(absolute_path(checkpoint["original_output"]))
        != checkpoint["original_artifacts_hash"]
    ):
        raise ValueError("original evidence changed during preparation")
    return output


def verify_continuation_assets(path, cases, *, check_original=False):
    path = absolute_path(path)
    value = read_json(path / "continuation.json")
    if set(value) != {
        "version",
        "checkpoint",
        "checkpoint_hash",
        "source_delta",
        "current_source_files",
        "new_pack_hash",
        "calibration_reused",
        "prefix_slots",
        "suffix_slots",
    }:
        raise ValueError("invalid continuation descriptor")
    checkpoint = value["checkpoint"]
    if (
        value["version"] != 1
        or value["prefix_slots"] != 54
        or value["suffix_slots"] != 66
        or value["calibration_reused"] is not True
        or digest(checkpoint) != value["checkpoint_hash"]
        or source_files() != value["current_source_files"]
        or verify_source_change(checkpoint) != value["source_delta"]
    ):
        raise ValueError("continuation checkpoint/source changed")
    _checkpoint_runtime(checkpoint)
    new = verify_pack(path, cases)
    original_path = absolute_path(checkpoint["pack"])
    if file_hash(original_path / "pack.json") != checkpoint["pack_file_hash"]:
        raise ValueError("original pack changed")
    old = read_json(original_path / "pack.json")
    expected = copy.deepcopy(old)
    expected["identity"]["runtime"] = new["identity"]["runtime"]
    expected["identity_hash"] = digest(expected["identity"])
    if new != expected or new["identity_hash"] != value["new_pack_hash"]:
        raise ValueError("rebase changed something other than runtime identity")
    if check_original:
        original_records(checkpoint, check_tree=True)
    return new, value
