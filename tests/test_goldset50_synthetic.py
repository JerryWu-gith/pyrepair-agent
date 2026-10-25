"""Structural and real-subprocess calibration for two self-authored tasks only."""

import ast
from pathlib import Path

from benchmarks.evaluation.cases import load_cases, prepare_case
from benchmarks.evaluation.grading import read_probe, validate_case

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/manifest_synthetic_extra2.json"


def new_cases():
    assert MANIFEST.is_file(), "extra-two synthetic manifest is not prepared"
    return {case.id: case for case in load_cases(MANIFEST)}


def test_extra_two_public_trees_hide_acceptance_and_references(tmp_path):
    cases = new_cases()
    assert set(cases) == {"config_merge", "multi_transfer"}
    existing = {case.id for case in load_cases(ROOT / "benchmarks/manifest_synthetic_v3.json")}
    assert not existing.intersection(cases)
    for case in cases.values():
        assert (case.revision, case.source_kind, case.suite, case.split) == (
            1, "synthetic", "capability", "dev"
        )
        assert case.timeout_seconds == 30
        production = {
            path.relative_to(case.buggy).as_posix()
            for path in (case.buggy / "src").rglob("*.py")
        }
        assert set(case.allowed_source_paths) == production
        public = prepare_case(case, tmp_path / case.id)
        assert (public / "TASK.md").read_bytes() == case.description.read_bytes()
        assert not (public / "hidden_tests").exists()
        assert not list(public.rglob("*.patch"))
        assert not list(public.rglob("provenance.json"))
        declared = set(case.fail_to_pass + case.pass_to_pass)
        defined = set()
        for relative in case.visible_tests + case.hidden_tests:
            base = case.buggy if relative in case.visible_tests else case.private
            tree = ast.parse((base / relative).read_text("utf-8"))
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    assert not node.decorator_list, "node IDs must be explicit and unparameterized"
                    defined.add(f"{relative}::{node.name}")
        assert declared == defined


def assert_real_calibration(case, destination):
    result = validate_case(case, destination)
    assert result["status"] == "valid", result
    assert result["system_error"] is False
    baseline = result["baseline"]
    assert baseline["returncode"] == 1
    assert {node for node, outcome in baseline["outcomes"].items() if outcome == "failed"} == set(
        case.fail_to_pass
    )
    probe = read_probe(destination / "baseline.probe.json")
    failed_calls = {
        row["nodeid"]
        for row in probe["reports"]
        if row["when"] == "call" and row["outcome"] == "failed"
    }
    assert failed_calls == set(case.fail_to_pass)
    assert "AssertionError" in (destination / "baseline.log").read_text("utf-8")
    assert result["reference"]["status"] == "passed"
    assert result["reference"]["visible"]["passed"] is True
    assert result["reference"]["hidden"]["passed"] is True
    assert result["mutant"]["status"] == "hidden_failed"
    assert result["mutant"]["visible"]["passed"] is True
    assert any(value == "failed" for value in result["mutant"]["hidden"]["outcomes"].values())


def test_config_merge_buggy_reference_and_incomplete_obey_real_acceptance(tmp_path):
    assert_real_calibration(new_cases()["config_merge"], tmp_path / "config_merge")


def test_transfer_buggy_reference_and_incomplete_obey_real_acceptance(tmp_path):
    assert_real_calibration(new_cases()["multi_transfer"], tmp_path / "multi_transfer")
