"""Fixed fifty-task live profile; authority and verification precede credentials."""

from __future__ import annotations

import json

from . import goldset_jobs, live_comparison
from .comparison_pack import comparison_config, file_hash, paired_slots
from .container_protocol import read_json
from .experiment import digest
from .live_plan import SLOT_LIMITS, _overlaps, absolute_path


def verify_goldset_pack(pack_path, cases):
    # Preparation/CLI owns this verifier; importing inspection never requires it.
    from .goldset_pack import verify_goldset_pack as verify

    return verify(pack_path, cases)


def describe_plan(pack_path, pack, output, mode, call_limit):
    """Describe only the exact registered fifty-case, three-trial formal profile."""
    pack_path, output = absolute_path(pack_path), absolute_path(output)
    if (
        not isinstance(pack, dict)
        or set(pack) != {"identity", "identity_hash"}
        or not isinstance(pack["identity"], dict)
        or digest(pack["identity"]) != pack["identity_hash"]
        or read_json(pack_path / "pack.json") != pack
    ):
        raise ValueError("invalid frozen goldset live pack")
    identity = pack["identity"]
    entries = identity.get("cases")
    expected = goldset_jobs.profile_entries()
    config = comparison_config("deepseek-flash", 3)
    if (
        type(identity.get("version")) is not int
        or identity["version"] != 2
        or identity.get("authorization") != "offline-only"
        or identity.get("config") != config
        or digest(identity["config"]) != digest(config)
        or not isinstance(entries, list)
        or len(entries) != 50
        or len(expected) != 50
        or any(
            not isinstance(entry, dict)
            or type(entry.get("revision")) is not int
            or any(entry.get(field) != registered[field] for field in registered)
            for entry, registered in zip(entries, expected, strict=True)
        )
    ):
        raise ValueError("goldset live comparison requires the fixed ordered fifty-case profile")
    slots = identity.get("slots")
    if (
        mode != "formal"
        or slots != paired_slots([entry["id"] for entry in expected], 3)
        or any(type(slot.get("trial")) is not int for slot in slots)
    ):
        raise ValueError("goldset live comparison requires the formal 300-slot schedule")
    maximum = sum(SLOT_LIMITS[slot["method"]] for slot in slots)
    if maximum != goldset_jobs.MAXIMUM_CALLS:
        raise ValueError("goldset live maximum changed")
    goldset_jobs._check_limit(call_limit)
    if _overlaps(pack_path, output):
        raise ValueError("execution output overlaps frozen pack")
    return json.loads(
        json.dumps(
            {
                "version": 1,
                "kind": "pyrepair-goldset50-live-comparison",
                "profile": goldset_jobs.PROFILE,
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


def inspect_execution(pack_path, cases, output, mode, call_limit):
    return live_comparison.inspect_execution(
        pack_path,
        cases,
        output,
        mode,
        call_limit,
        pack_verifier=verify_goldset_pack,
        plan_describer=describe_plan,
    )


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
    return live_comparison.execute_comparison(
        pack_path,
        cases,
        output,
        mode,
        call_limit,
        authorization,
        resume=resume,
        offline_executor=offline_executor,
        credential_getter=credential_getter,
        pack_verifier=verify_goldset_pack,
        plan_describer=describe_plan,
        job_builder=goldset_jobs.public_job,
    )
