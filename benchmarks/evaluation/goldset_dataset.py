"""One explicit fifty-task selection; no model, Docker or source execution."""

from __future__ import annotations

from pathlib import Path

from .cases import case_fingerprint, contained, load_cases, public_files
from .catalog_source_cache import (
    canonical,
    checked_root,
    json_bytes,
    read_bounded,
    sha256,
    write_new_json,
)
from .source_catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "opensource_catalog30.json"
SYNTHETIC_IDS = (
    *[f"case_{n:02d}" for n in range(1, 16)],
    "multi_orders",
    "multi_inventory",
    "multi_time",
    "config_merge",
    "multi_transfer",
)


def validate_selection(cases) -> dict:
    catalog = load_catalog(CATALOG)
    entries = catalog["entries"]
    expected_ids = [*SYNTHETIC_IDS, *(e["id"] for e in entries)]
    if len(cases) != 50 or [c.id for c in cases] != expected_ids or len(set(expected_ids)) != 50:
        raise ValueError(
            "goldset requires the exact ordered twenty synthetic plus thirty source identities"
        )
    for case in cases[:20]:
        if (case.source_kind, case.split, case.revision) != (
            "synthetic",
            "dev",
            2 if case.id == "case_15" else 1,
        ):
            raise ValueError("synthetic source, split or revision changed")
    for case, entry in zip(cases[20:], entries, strict=True):
        if (
            (case.source_kind, case.split, case.revision)
            != ("opensource", entry["split"], entry["revision"] + bool(entry["legacy_manifest"]))
            or any(
                case.origin.get(k) != entry[k]
                for k in ("repository", "buggy_commit", "fixed_commit")
            )
            or case.origin.get("catalog_entry_sha256") != sha256(canonical(entry))
        ):
            raise ValueError("opensource task provenance, split or revision changed")
    return {"case_count": 50, "synthetic_dev": 20, "opensource_dev": 2, "opensource_holdout": 28}


def _overlap(first, second):
    return first.is_relative_to(second) or second.is_relative_to(first)


def _receipt(cases, manifest):
    return {
        "version": 1,
        "kind": "pyrepair-goldset50-dataset",
        **validate_selection(cases),
        "source_catalog_sha256": sha256(read_bounded(CATALOG)),
        "manifest_sha256": sha256(read_bounded(manifest)),
        "case_fingerprints": {c.id: case_fingerprint(c) for c in cases},
        "calibration_status": "separate_evidence_required",
        "ready_for_model_evaluation": False,
    }


def assemble_dataset(manifests: list[Path], output: Path) -> Path:
    """Preserve relative metadata and fingerprints while copying separated trees."""
    output = checked_root(output).resolve()
    if output.exists():
        raise FileExistsError("unified dataset output already exists")
    inputs = [checked_root(p).resolve() for p in manifests]
    cases = [case for p in inputs for case in load_cases(p)]
    validate_selection(cases)
    if any(_overlap(output, p.parent) for p in inputs):
        raise ValueError("unified output overlaps source assets")
    public = [c.buggy.resolve() for c in cases]
    private = [c.private.resolve() for c in cases]
    if any(_overlap(p, q) for p in public for q in private):
        raise ValueError("cross-task public and private assets overlap")
    fingerprints = {c.id: case_fingerprint(c) for c in cases}
    # Check destination-path overlap too, as input manifests may have different roots.
    destinations = [(output / c.buggy_path).resolve() for c in cases]
    secrets = [(output / c.private_path).resolve() for c in cases]
    if any(_overlap(p, q) for p in destinations for q in secrets) or any(
        _overlap(a, b)
        for group in (destinations, secrets)
        for i, a in enumerate(group)
        for b in group[i + 1 :]
    ):
        raise ValueError("rebased task asset paths overlap")
    output.mkdir(parents=True, exist_ok=False)
    try:
        for case in cases:
            for source_root, relative in (
                (case.buggy, case.buggy_path),
                (case.private, case.private_path),
            ):
                for source in public_files(source_root):
                    target = contained(
                        output, relative + "/" + source.relative_to(source_root).as_posix()
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(source.read_bytes())
            target = contained(output, case.public_description_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(case.description.read_bytes())
        manifest = output / "manifest.json"
        write_new_json(manifest, {"version": 2, "cases": [c.metadata() for c in cases]})
        copied = load_cases(manifest)
        if fingerprints != {c.id: case_fingerprint(c) for c in copied} or fingerprints != {
            c.id: case_fingerprint(c) for c in cases
        }:
            raise ValueError("task assets changed during unified assembly")
        write_new_json(output / "dataset.json", _receipt(copied, manifest))
        return manifest
    except BaseException as exc:
        write_new_json(
            output / "assembly-error.json",
            {"status": "incomplete", "error_type": type(exc).__name__},
        )
        raise


def verify_dataset(path: Path):
    path = checked_root(path).resolve()
    manifest = path / "manifest.json"
    cases = load_cases(manifest)
    if json_bytes(read_bounded(path / "dataset.json")) != _receipt(cases, manifest):
        raise ValueError("unified dataset identity changed")
    return cases
