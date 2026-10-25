"""Prepare source/reference evidence only, never a runnable task or model experiment."""

from __future__ import annotations

import difflib
from pathlib import Path
from uuid import uuid4

from .cases import contained, is_link
from .catalog_source_cache import (
    canonical,
    checked_root,
    json_bytes,
    prepare_version,
    read_bounded,
    sha256,
    verify_version,
    version_path,
    write_new_json,
)
from .opensource_assets import _snapshot_files, _source_patch, fetch_bytes
from .patching import patch_paths
from .source_catalog import validate_catalog


def _identity(catalog, output):
    data = validate_catalog(catalog)
    saved = json_bytes(read_bounded(output / "catalog.json"))
    if saved != data:
        raise ValueError("source catalog changed; cannot reuse this batch")
    return data


def _reference_patch(old, new, paths):
    if all(old[p].endswith(b"\n") and new[p].endswith(b"\n") for p in paths):
        return _source_patch(old, new, paths)
    chunks = []
    for path in paths:
        before = old[path].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        after = new[path].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        for line in difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile="a/" + path,
            tofile="b/" + path,
        ):
            chunks.append(
                line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            )
    result = "".join(chunks)
    if patch_paths(result) != tuple(paths):
        raise ValueError("reference patch path mismatch")
    return result


def _reference(entry, buggy, fixed, output):
    old = _snapshot_files(Path(buggy["path"]) / "source")
    new = _snapshot_files(Path(fixed["path"]) / "source")
    root = entry["source_root"] + "/"
    changed = {
        p
        for p in set(old) | set(new)
        if p.startswith(root) and p.endswith(".py") and old.get(p) != new.get(p)
    }
    if changed != set(entry["reference_source_paths"]):
        raise ValueError("actual production changes differ from registered reference paths")
    if any(p not in old or p not in new for p in changed):
        raise ValueError("production file creation/deletion is outside the current repair contract")
    patch = _reference_patch(old, new, entry["reference_source_paths"])
    report = {
        "version": 1,
        "case_id": entry["id"],
        "status": "reference_prepared",
        "catalog_entry_sha256": sha256(canonical(entry)),
        "repository": entry["repository"],
        "buggy_version": Path(buggy["path"]).relative_to(output).as_posix(),
        "fixed_version": Path(fixed["path"]).relative_to(output).as_posix(),
        "gold_patch_sha256": sha256(patch.encode("utf-8")),
        "reference_source_paths": entry["reference_source_paths"],
        "licenses": {"buggy": buggy["licenses"], "fixed": fixed["licenses"]},
        "calibration_status": "not_run",
        "ready_for_model_evaluation": False,
    }
    return report, patch.encode("utf-8")


def _check_case(root, report, patch):
    if json_bytes(read_bounded(root / "reference.json")) != report:
        raise ValueError("recorded reference differs from verified source")
    if read_bounded(root / "gold.patch") != patch:
        raise ValueError("cached reference patch differs from verified source")


def _case_directories(data, output, *, complete):
    cases = checked_root(output / "cases")
    if not cases.exists():
        if complete:
            raise ValueError("reference cases are missing")
        return
    actual = set()
    for path in cases.iterdir():
        if is_link(path) or not path.is_dir():
            raise ValueError("unexpected reference case entry")
        actual.add(path.name)
    expected = {e["id"] for e in data["entries"]}
    if not actual <= expected or (complete and actual != expected):
        raise ValueError("reference case set differs from source catalog")


def _summary(data, versions):
    return {
        "version": 1,
        "status": "references_prepared",
        "catalog_sha256": sha256(canonical(data)),
        "reference_count": len(data["entries"]),
        "unique_version_count": len(versions),
        "case_ids": [e["id"] for e in data["entries"]],
        "calibration_status": "not_run",
        "ready_for_model_evaluation": False,
        "model_calls": 0,
        "upstream_code_executed": False,
    }


def verify_references(catalog: dict, output: Path) -> dict:
    """Recompute cache and reference evidence without network or filesystem writes."""
    output = checked_root(output)
    data = _identity(catalog, output)
    _case_directories(data, output, complete=True)
    versions = {}
    for entry in data["entries"]:
        pair = {}
        for label in ("buggy", "fixed"):
            result = verify_version(entry, label, output / "versions")
            pair[label] = result
            versions[(result["repository"], result["commit"])] = result
        report, patch = _reference(entry, pair["buggy"], pair["fixed"], output)
        _check_case(contained(output, "cases/" + entry["id"]), report, patch)
    return _summary(data, versions)


def prepare_references(
    catalog: dict, output: Path, *, fetch=fetch_bytes, resume=False, progress=None
) -> dict:
    """Explicit preparation/resume; prior failed runs and completed data are preserved."""
    data = validate_catalog(catalog)
    output = checked_root(output)
    if resume:
        _identity(data, output)
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_new_json(output / "catalog.json", data)
    lock = output / "writer.lock"
    owner = uuid4().hex.encode("ascii")
    with lock.open("xb") as stream:
        stream.write(owner)
    run = output / "runs" / uuid4().hex
    state = {
        "status": "interrupted",
        "catalog_sha256": sha256(canonical(data)),
        "completed_cases": [],
    }
    try:
        run.mkdir(parents=True, exist_ok=False)
        _case_directories(data, output, complete=False)
        # Validate every existing role binding before fetching anything new.
        versions, roles = {}, {}
        for entry in data["entries"]:
            for label in ("buggy", "fixed"):
                if version_path(entry, label, output / "versions").exists():
                    verified = verify_version(entry, label, output / "versions")
                    roles[(entry["id"], label)] = verified
                    versions[(verified["repository"], verified["commit"])] = verified
            root = contained(output, "cases/" + entry["id"])
            if root.exists():
                if any((entry["id"], label) not in roles for label in ("buggy", "fixed")):
                    raise ValueError("reference has missing source cache")
                report, patch = _reference(
                    entry, roles[(entry["id"], "buggy")], roles[(entry["id"], "fixed")], output
                )
                _check_case(root, report, patch)
        for entry in data["entries"]:
            state["active_case"] = entry["id"]
            pair = {}
            for label in ("buggy", "fixed"):
                key = entry["id"], label
                result = roles.get(key)
                if result is None:
                    result = prepare_version(entry, label, output / "versions", fetch=fetch)
                    roles[key] = result
                pair[label] = result
                versions[(result["repository"], result["commit"])] = result
            report, patch = _reference(entry, pair["buggy"], pair["fixed"], output)
            target = contained(output, "cases/" + entry["id"])
            if target.exists():
                _check_case(target, report, patch)
            else:
                target.mkdir(parents=True, exist_ok=False)
                with (target / "gold.patch").open("xb") as stream:
                    stream.write(patch)
                if read_bounded(target / "gold.patch") != patch:
                    raise ValueError("published reference bytes differ from verified source")
                # Written last: an incomplete directory is not a prepared case.
                write_new_json(target / "reference.json", report)
            state["completed_cases"].append(entry["id"])
            if progress is not None:
                progress(entry["id"])
        result = _summary(data, versions)
        state.update(status="references_prepared", summary=result)
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        state.update(
            status="source_error", error={"type": type(exc).__name__, "message": str(exc)[:1200]}
        )
        raise
    finally:
        try:
            if run.is_dir():
                write_new_json(run / "report.json", state)
        finally:
            if read_bounded(lock) != owner:
                raise ValueError("writer lock owner changed; lock retained")
            lock.unlink()
