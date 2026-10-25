"""Freeze the explicit fifty-task dataset with matching saved calibration evidence."""

from __future__ import annotations

from pathlib import Path

from .cases import case_fingerprint
from .catalog_calibration import _check, _full_collection, collect_calibrations
from .catalog_source_cache import checked_root, json_bytes, read_bounded, sha256, write_new_json
from .comparison_pack import environment_identity, prepare_pack, verify_pack
from .experiment import digest
from .goldset_dataset import validate_selection, verify_dataset
from .layered_assets import load_regression


def calibration_reuser(index: dict):
    """Create data-only capsules, not copies of every Docker input/source tree."""
    if index.get("status") != "calibrations_verified":
        raise ValueError("verified calibration index required")
    rows = {r["case_id"]: r for r in index["cases"]}
    if len(rows) != index["case_count"]:
        raise ValueError("duplicate calibration rows")

    def reuse(case, output, environment):
        row = rows[case.id]
        fingerprint = case_fingerprint(case)
        if (
            row["fingerprint"] != fingerprint
            or row["environment_hash"] != environment["verified_hash"]
        ):
            raise ValueError("reused calibration task or environment changed")
        raw = read_bounded(Path(row["validation_path"]))
        if sha256(raw) != row["validation_sha256"]:
            raise ValueError("source calibration bytes changed")
        record = json_bytes(raw)
        if (record.get("case_id"), record.get("fingerprint")) != (case.id, fingerprint):
            raise ValueError("source calibration identity changed")
        _check(case, record, environment["verified_hash"])
        collection, _additional = _full_collection(case, record)
        output = checked_root(output).resolve()
        output.mkdir(parents=True, exist_ok=False)
        with (output / "raw-validation.json").open("xb") as stream:
            stream.write(raw)
        write_new_json(
            output / "reuse.json",
            {
                "case_id": case.id,
                "fingerprint": fingerprint,
                "environment_hash": environment["verified_hash"],
                "source_validation_path": row["validation_path"],
                "source_validation_sha256": row["validation_sha256"],
                "scope": "Identical saved core calibration, not new model performance",
                "core_collection": collection,
            },
        )
        return {
            "status": "valid",
            "core": [{"case_id": case.id, "status": "valid", "fingerprint": fingerprint}],
            "extended": None,
            "regression_identity": digest(None),
            "evidence": {"raw-validation.json": sha256(raw)},
            "core_collection": collection,
        }

    return reuse


def prepare_goldset_pack(
    dataset_path: Path, output: Path, environment_lock: Path, calibration_roots: list[Path]
) -> Path:
    dataset_path, output = checked_root(dataset_path).resolve(), checked_root(output).resolve()
    if output.is_relative_to(dataset_path) or dataset_path.is_relative_to(output):
        raise ValueError("frozen pack output overlaps the unified dataset")
    cases = verify_dataset(dataset_path)
    environment = environment_identity(environment_lock)
    if any(load_regression(c) is not None for c in cases):
        raise ValueError("this goldset profile requires its declared core contract scope")
    index = collect_calibrations(
        cases, calibration_roots, environment["verified_hash"], include_synthetic=True
    )
    result = prepare_pack(
        cases,
        output,
        environment_lock,
        "deepseek-flash",
        3,
        calibration_reuser=calibration_reuser(index),
    )
    verify_goldset_pack(result, cases)
    return result


def verify_goldset_pack(pack_path: Path, cases: list) -> dict:
    pack_path = checked_root(pack_path).resolve()
    validate_selection(cases)
    roots = {case.root.resolve() for case in cases}
    if len(roots) != 1:
        raise ValueError("goldset cases must come from one assembled dataset")
    actual = verify_dataset(next(iter(roots)))
    if [c.metadata() for c in actual] != [c.metadata() for c in cases]:
        raise ValueError("provided cases differ from the unified dataset")
    pack = verify_pack(pack_path, cases)
    environment = pack["identity"]["environment"]["verified_hash"]
    for case, entry in zip(cases, pack["identity"]["cases"], strict=True):
        control = Path(pack_path) / "control" / Path(entry["public"]).name / "v"
        raw = read_bounded(control / "raw-validation.json")
        record = json_bytes(raw)
        receipt = json_bytes(read_bounded(control / "reuse.json"))
        if (
            (record.get("case_id"), record.get("fingerprint")) != (case.id, entry["fingerprint"])
            or receipt.get("fingerprint") != entry["fingerprint"]
            or receipt.get("environment_hash") != environment
            or receipt.get("source_validation_sha256") != sha256(raw)
        ):
            raise ValueError("frozen calibration capsule identity changed")
        _check(case, record, environment)
        collection, _additional = _full_collection(case, record)
        if (
            entry.get("core_collection") != collection
            or receipt.get("core_collection") != collection
        ):
            raise ValueError("frozen complete core collection changed")
    return pack
