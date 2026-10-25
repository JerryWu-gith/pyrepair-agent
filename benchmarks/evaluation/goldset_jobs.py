"""Explicit public worker authority for the fixed fifty-task goldset profile."""

from __future__ import annotations

from collections import Counter

from . import live_plan
from .comparison_pack import comparison_config
from .experiment import digest
from .goldset_dataset import CATALOG, SYNTHETIC_IDS
from .source_catalog import load_catalog

PROFILE = "goldset50-r1"
MAXIMUM_CALLS = 5550


def profile_entries():
    """Read registered metadata only; never execute source tasks or inspect keys."""
    entries = [
        {
            "id": name,
            "revision": 2 if name == "case_15" else 1,
            "source_kind": "synthetic",
            "split": "dev",
        }
        for name in SYNTHETIC_IDS
    ] + [
        {
            "id": entry["id"],
            "revision": entry["revision"] + bool(entry["legacy_manifest"]),
            "source_kind": "opensource",
            "split": entry["split"],
        }
        for entry in load_catalog(CATALOG)["entries"]
    ]
    if len(entries) != 50 or Counter((e["source_kind"], e["split"]) for e in entries) != {
        ("synthetic", "dev"): 20,
        ("opensource", "dev"): 2,
        ("opensource", "holdout"): 28,
    }:
        raise ValueError("registered goldset profile groups changed")
    return entries


def _check_limit(value):
    if type(value) is not int or not 1 <= value <= MAXIMUM_CALLS:
        raise ValueError("invalid goldset public worker call limit")


def public_job(pack_path, pack, slot, folder, quota, call_limit):
    """Build via the unchanged public-only capability, then explicitly upgrade it."""
    _check_limit(call_limit)
    job = live_plan.public_job(pack_path, pack, slot, folder, quota, min(call_limit, 2220))
    return validate_job({**job, "version": 2, "profile": PROFILE, "call_limit": call_limit})


def validate_job(job):
    """Reuse all V1 evidence/path/environment checks without widening V1 authority."""
    if (
        not isinstance(job, dict)
        or type(job.get("version")) is not int
        or job["version"] != 2
        or job.get("profile") != PROFILE
        or job.get("config") != comparison_config("deepseek-flash", 3)
        or digest(job["config"]) != digest(comparison_config("deepseek-flash", 3))
    ):
        raise ValueError("invalid goldset public worker job")
    _check_limit(job.get("call_limit"))
    normalized = {key: value for key, value in job.items() if key != "profile"}
    normalized.update(version=1, call_limit=min(job["call_limit"], 2220))
    live_plan.validate_job(normalized)
    spec = job["spec"]
    expected = next((entry for entry in profile_entries() if entry["id"] == spec["case_id"]), None)
    if expected is None or any(
        spec[field] != expected[field] for field in ("revision", "source_kind")
    ):
        raise ValueError("worker task is outside the fixed goldset profile")
    return job
