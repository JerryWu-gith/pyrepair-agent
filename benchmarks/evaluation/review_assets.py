"""Versioned selected-asset binding for fixed Review experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .cases import (
    EvaluationCase,
    case_fingerprint,
    contained,
    is_link,
    load_cases,
    public_files,
    safe_relative,
)
from .experiment import ROOT, digest


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_hash(fixtures: Path) -> str:
    if not fixtures.is_dir() or is_link(fixtures):
        raise ValueError("asset fixtures directory missing or linked")
    hashes = {p.relative_to(fixtures).as_posix(): file_hash(p) for p in public_files(fixtures)}
    manifest = json.loads(contained(fixtures, "manifest.json").read_text(encoding="utf-8"))
    # Generic tree walking ignores caches/environment paths. Explicitly selected
    # executable assets must still be bound, even when their names are ignored.
    for row in manifest["candidates"]:
        for field in ("patch", "precision_test"):
            if field in row:
                relative = safe_relative(row[field])
                hashes[relative] = file_hash(contained(fixtures, relative))
    return digest(hashes)


def _case_asset_hash(case: EvaluationCase) -> str:
    return digest(
        {
            "tree": case_fingerprint(case),
            "declared_hidden": {
                relative: file_hash(contained(case.private, relative))
                for relative in case.hidden_tests
            },
        }
    )


def _locator(path: Path) -> dict:
    if any(is_link(p) for p in (path, *path.parents)):
        raise ValueError("asset links are not supported")
    path = path.resolve(strict=True)
    if path.is_relative_to(ROOT):
        return {"kind": "repository", "path": path.relative_to(ROOT).as_posix()}
    return {"kind": "external", "path": str(path)}


def _resolve(locator: dict) -> Path:
    if not isinstance(locator, dict) or set(locator) != {"kind", "path"}:
        raise ValueError("invalid asset locator")
    if not isinstance(locator["path"], str) or not locator["path"]:
        raise ValueError("invalid asset path")
    if locator["kind"] == "repository":
        path = contained(ROOT, locator["path"])
    elif locator["kind"] == "external" and Path(locator["path"]).is_absolute():
        path = Path(locator["path"])
    else:
        raise ValueError("invalid asset locator kind/path")
    if any(is_link(p) for p in (path, *path.parents)):
        raise ValueError("asset links are not supported")
    return path.resolve(strict=True)


def make_asset_binding(cases_manifest: Path, fixtures: Path, case_ids: list[str]) -> dict:
    cases = {case.id: case for case in load_cases(cases_manifest)}
    if not case_ids or len(set(case_ids)) != len(case_ids) or not set(case_ids) <= cases.keys():
        raise ValueError("invalid asset case selection")
    return {
        "version": 1,
        "fixtures": _locator(fixtures),
        "cases_manifest": _locator(cases_manifest),
        "fixture_hash": fixture_hash(fixtures),
        "manifest_hash": file_hash(cases_manifest),
        "cases": {key: _case_asset_hash(cases[key]) for key in sorted(case_ids)},
    }


def validate_asset_binding(binding: dict) -> Path:
    try:
        if (
            not isinstance(binding, dict)
            or set(binding)
            != {"version", "fixtures", "cases_manifest", "fixture_hash", "manifest_hash", "cases"}
            or type(binding["version"]) is not int
            or binding["version"] != 1
            or not isinstance(binding["cases"], dict)
            or not binding["cases"]
        ):
            raise ValueError("invalid asset binding")
        fixtures = _resolve(binding["fixtures"])
        manifest = _resolve(binding["cases_manifest"])
        current = make_asset_binding(manifest, fixtures, list(binding["cases"]))
        if digest(binding) != digest(current):
            raise ValueError("asset identity changed; prepare again")
        return fixtures
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("asset identity unavailable, invalid or changed; prepare again") from exc


def validate_dataset(dataset: dict, candidate_ids: list[str]) -> None:
    """Only this synthetic/dev extension is supported, without user-supplied counts."""
    if (
        not isinstance(dataset, dict)
        or set(dataset) != {"id", "source_kind", "split", "candidate_cases"}
        or dataset["source_kind"] != "synthetic"
        or dataset["split"] != "dev"
        or not isinstance(dataset["candidate_cases"], dict)
        or not candidate_ids
        or set(dataset["candidate_cases"]) != set(candidate_ids)
    ):
        raise ValueError("invalid dataset metadata/mapping")
    for identity in (dataset["id"], *candidate_ids, *dataset["candidate_cases"].values()):
        try:
            safe_relative(identity)
        except ValueError as exc:
            raise ValueError("invalid dataset identity") from exc
        if "/" in identity:
            raise ValueError("invalid dataset identity")


def dataset_metadata(manifest: dict) -> dict | None:
    if "dataset" not in manifest:
        return None
    metadata = manifest["dataset"]
    if not isinstance(metadata, dict) or set(metadata) != {"id", "source_kind", "split"}:
        raise ValueError("invalid dataset fields")
    result = {
        **metadata,
        "candidate_cases": {r["id"]: r["case_id"] for r in manifest["candidates"]},
    }
    validate_dataset(result, [r["id"] for r in manifest["candidates"]])
    return result
