"""Side-effect-free live plans and explicit authority; never loads credentials."""

from __future__ import annotations

import json
from pathlib import Path

from .agent_input import PublicTaskSpec, validate_public_input
from .cases import contained
from .comparison_budget import checked_path
from .comparison_evidence import read_evidence
from .comparison_pack import comparison_config, environment_identity, file_hash, paired_slots
from .container_protocol import read_json
from .experiment import digest

SLOT_LIMITS = {"single-shot": 1, "full-agent": 36}
SMOKE_CASE = "os_more_seekable_1269"


def absolute_path(value):
    return checked_path(checked_path(Path(value)).resolve())


def _overlaps(first, second):
    return first.is_relative_to(second) or second.is_relative_to(first)


def describe_plan(pack_path, pack, output, mode, call_limit):
    """Describe a verified pack, without creating approval, output, quota or a client."""
    pack_path, output = absolute_path(pack_path), absolute_path(output)
    if (
        not isinstance(pack, dict)
        or set(pack) != {"identity", "identity_hash"}
        or digest(pack["identity"]) != pack["identity_hash"]
        or read_json(pack_path / "pack.json") != pack
    ):
        raise ValueError("invalid frozen live pack")
    identity = pack["identity"]
    config = comparison_config("deepseek-flash", 3)
    if (
        identity.get("version") != 2
        or identity.get("authorization") != "offline-only"
        or identity.get("config") != config
        or not isinstance(identity.get("cases"), list)
        or len(identity["cases"]) != 20
        or identity.get("slots") != paired_slots([e["id"] for e in identity["cases"]], 3)
    ):
        raise ValueError("live comparison requires the fixed 20-case/three-trial pack")
    if mode == "formal":
        slots = identity["slots"]
    elif mode == "smoke":
        entry = next((e for e in identity["cases"] if e["id"] == SMOKE_CASE), None)
        if entry is None or entry.get("revision") != 2 or entry.get("source_kind") != "opensource":
            raise ValueError("smoke requires the frozen more r2 task")
        slots = [s for s in identity["slots"] if s["case_id"] == SMOKE_CASE and s["trial"] == 1]
        if len(slots) != 2:
            raise ValueError("invalid smoke pair")
    else:
        raise ValueError("invalid execution mode")
    maximum = sum(SLOT_LIMITS[s["method"]] for s in slots)
    if type(call_limit) is not int or not 1 <= call_limit <= maximum:
        raise ValueError("invalid global call limit")
    if _overlaps(pack_path, output):
        raise ValueError("execution output overlaps frozen pack")
    return json.loads(
        json.dumps(
            {
                "version": 1,
                "kind": "pyrepair-controlled-live-comparison",
                "mode": mode,
                "pack_path": str(pack_path),
                "pack_hash": pack["identity_hash"],
                "pack_file_hash": file_hash(pack_path / "pack.json"),
                "output": str(output),
                "slots": slots,
                "config": config,
                "runtime": identity["runtime"],
                "environment": identity["environment"],
                "call_limit": call_limit,
                "slot_limits": SLOT_LIMITS,
                "maximum_slot_calls": maximum,
                "cost_limit_rmb": None,
                "http_transport_count": None,
            }
        )
    )


def validate_authorization(value, expected):
    """A local approval is an accident barrier, not proof against a malicious host."""
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "approved", "plan", "plan_hash", "human_confirmation"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["approved"] is not True
        or not isinstance(value["human_confirmation"], str)
        or not 1 <= len(value["human_confirmation"].strip()) <= 500
        or not isinstance(value["plan"], dict)
        or value["plan_hash"] != digest(value["plan"])
        or digest(value["plan"]) != digest(expected)
    ):
        raise ValueError("missing or changed execution authorization")
    return expected


def public_job(pack_path, pack, slot, folder, quota, call_limit):
    if slot not in pack["identity"]["slots"]:
        raise ValueError("worker slot is not in frozen plan")
    entry = next(e for e in pack["identity"]["cases"] if e["id"] == slot["case_id"])
    public = contained(absolute_path(pack_path), entry["public"])
    if (
        file_hash(public / "spec.json") != entry["spec_hash"]
        or file_hash(public / "evidence.json") != entry["evidence_hash"]
    ):
        raise ValueError("public worker files no longer match frozen evidence")
    job = {
        "version": 1,
        "repo": str(absolute_path(public / "r")),
        "spec": read_json(public / "spec.json"),
        "evidence": read_json(public / "evidence.json"),
        "slot": slot,
        "output": str(absolute_path(folder)),
        "quota": str(absolute_path(quota)),
        "call_limit": call_limit,
        "environment": pack["identity"]["environment"],
        "config": pack["identity"]["config"],
    }
    spec = PublicTaskSpec.from_dict(job["spec"])
    if (spec.case_id, spec.revision, spec.source_kind) != (
        entry["id"],
        entry["revision"],
        entry["source_kind"],
    ):
        raise ValueError("public worker descriptor no longer matches frozen identity")
    return validate_job(job)


def validate_job(job):
    """Validate the entire public capability before any provider can be constructed."""
    if (
        not isinstance(job, dict)
        or set(job)
        != {
            "version",
            "repo",
            "spec",
            "evidence",
            "slot",
            "output",
            "quota",
            "call_limit",
            "environment",
            "config",
        }
        or type(job["version"]) is not int
        or job["version"] != 1
        or job["config"] != comparison_config("deepseek-flash", 3)
        or type(job["call_limit"]) is not int
        or not 1 <= job["call_limit"] <= 2220
    ):
        raise ValueError("invalid public worker job")
    spec = PublicTaskSpec.from_dict(job["spec"])
    slot = job["slot"]
    if (
        not isinstance(slot, dict)
        or set(slot) != {"slot", "case_id", "method", "trial"}
        or slot["case_id"] != spec.case_id
        or slot["method"] not in SLOT_LIMITS
        or type(slot["trial"]) is not int
        or not 1 <= slot["trial"] <= 3
        or slot["slot"] != f"{spec.case_id}--{slot['trial']}--{slot['method']}"
    ):
        raise ValueError("worker slot does not match public descriptor")
    repo, output, quota = (absolute_path(job[n]) for n in ("repo", "output", "quota"))
    if any(
        str(p) != job[n]
        for n, p in zip(("repo", "output", "quota"), (repo, output, quota), strict=True)
    ):
        raise ValueError("worker paths must be canonical absolute paths")
    if _overlaps(repo, output) or _overlaps(repo, quota) or _overlaps(output, quota):
        raise ValueError("worker output/quota overlaps public input")
    validate_public_input(repo, spec)
    read_evidence(job["evidence"], spec)
    environment = job["environment"]
    if (
        not isinstance(environment, dict)
        or environment_identity(Path(environment["lock_path"])) != environment
    ):
        raise ValueError("worker environment changed")
    return job
