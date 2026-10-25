"""Owned file fixtures exercise unified selection/copying, not model execution."""

import importlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.evaluation.cases import case_fingerprint, load_cases
from benchmarks.evaluation.catalog_source_cache import canonical, sha256
from benchmarks.evaluation.source_catalog import load_catalog
from tests.evaluation_helpers import make_case

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = [
    *(f"case_{n:02d}" for n in range(1, 16)),
    "multi_orders",
    "multi_inventory",
    "multi_time",
    "config_merge",
    "multi_transfer",
]


def api():
    name = "benchmarks.evaluation.goldset_dataset"
    assert importlib.util.find_spec(name) is not None, "unified dataset missing"
    return importlib.import_module(name)


def selection(tmp_path):
    owned = load_cases(make_case(tmp_path / "owned"))[0]
    synthetic = [
        replace(owned, id=name, revision=2 if name == "case_15" else 1) for name in SYNTHETIC
    ]
    catalog = load_catalog(ROOT / "benchmarks/opensource_catalog30.json")
    opensource = [
        replace(
            owned,
            id=e["id"],
            source_kind="opensource",
            split=e["split"],
            revision=e["revision"] + bool(e["legacy_manifest"]),
            origin={
                "repository": e["repository"],
                "buggy_commit": e["buggy_commit"],
                "fixed_commit": e["fixed_commit"],
                "catalog_entry_sha256": sha256(canonical(e)),
            },
        )
        for e in catalog["entries"]
    ]
    return synthetic + opensource


def test_selection_preserves_exact_fifty_ids_source_split_and_revisions(tmp_path):
    result = api().validate_selection(selection(tmp_path))
    assert result["case_count"] == 50
    assert result["synthetic_dev"] == 20
    assert result["opensource_dev"] == 2
    assert result["opensource_holdout"] == 28


@pytest.mark.parametrize(
    "problem", ["duplicate", "missing", "split", "source", "revision", "provenance", "order"]
)
def test_wrong_fifty_selection_is_not_authorizable(tmp_path, problem):
    cases = selection(tmp_path)
    if problem == "duplicate":
        cases[-1] = cases[-2]
    elif problem == "missing":
        cases.pop()
    elif problem == "order":
        cases.reverse()
    elif problem == "split":
        cases[-1] = replace(cases[-1], split="dev")
    elif problem == "source":
        cases[-1] = replace(cases[-1], source_kind="synthetic")
    elif problem == "revision":
        cases[20] = replace(cases[20], revision=2)
    else:
        cases[-1] = replace(cases[-1], origin={**cases[-1].origin, "buggy_commit": "0" * 40})
    with pytest.raises(ValueError):
        api().validate_selection(cases)


def materialized_selection(tmp_path):
    cases = selection(tmp_path)
    root = tmp_path / "source"
    rows = []
    template = cases[0]
    for case in cases:
        public, private, description = (
            f"public/{case.id}",
            f"private/{case.id}",
            f"descriptions/{case.id}.md",
        )
        for source in template.buggy.rglob("*"):
            if source.is_file():
                target = root / public / source.relative_to(template.buggy)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        for source in template.private.rglob("*"):
            if source.is_file():
                target = root / private / source.relative_to(template.private)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        target = root / description
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(template.description.read_bytes())
        rows.append(
            {
                **case.metadata(),
                "buggy_path": public,
                "private_path": private,
                "public_description_path": description,
            }
        )
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"version": 2, "cases": rows}), encoding="utf-8")
    return manifest


def test_assembly_preserves_fingerprints_and_private_separation(tmp_path):
    manifest = materialized_selection(tmp_path)
    before = {c.id: case_fingerprint(c) for c in load_cases(manifest)}
    output = tmp_path / "unified"
    api().assemble_dataset([manifest], output)
    after = load_cases(output / "manifest.json")
    assert {c.id: case_fingerprint(c) for c in after} == before
    assert not any((c.buggy / "hidden_tests").exists() for c in after)
    assert json.loads((output / "dataset.json").read_text())["case_count"] == 50
    with pytest.raises(FileExistsError):
        api().assemble_dataset([manifest], output)


def test_dataset_output_alias_cannot_overlap_source_assets(tmp_path):
    manifest = materialized_selection(tmp_path)
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    output = sibling / ".." / "source" / "public" / SYNTHETIC[0] / "nested"
    with pytest.raises(ValueError, match="overlap"):
        api().assemble_dataset([manifest], output)
    assert not output.exists()


def test_unified_receipt_detects_post_assembly_private_asset_drift(tmp_path):
    manifest = materialized_selection(tmp_path)
    output = tmp_path / "unified"
    api().assemble_dataset([manifest], output)
    cases = api().verify_dataset(output)
    cases[0].wrong_patch.write_text("tampered")
    with pytest.raises(ValueError, match="identity"):
        api().verify_dataset(output)
