"""Exercise migrated precision acceptance using only self-authored tasks."""

from pathlib import Path

from benchmarks.evaluation.cases import case_fingerprint, load_cases, prepare_case
from benchmarks.evaluation.grading import grade_patch, validate_case

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "benchmarks/manifest_v2.json"
MIGRATED = ROOT / "benchmarks/manifest_synthetic_v3.json"
LONG_NODE = (
    "hidden_tests/test_acceptance.py::test_exact_cents_independent_of_decimal_context[long-prec28]"
)


def precision_case():
    assert MIGRATED.is_file(), "new precision manifest is not prepared"
    return next(case for case in load_cases(MIGRATED) if case.id == "case_15")


def test_migration_preserves_other_tasks_and_keeps_private_inputs_hidden(tmp_path):
    case = precision_case()
    old = {c.id: c for c in load_cases(ORIGINAL)}
    new = {c.id: c for c in load_cases(MIGRATED)}
    assert set(new) == set(old)
    for identity in old.keys() - {"case_15"}:
        assert new[identity].metadata() == old[identity].metadata()
        assert case_fingerprint(new[identity]) == case_fingerprint(old[identity])
    previous = old["case_15"]
    assert case.revision == previous.revision + 1
    assert case.private != previous.private
    assert case.buggy == previous.buggy
    assert case.description == previous.description
    assert case.visible_tests == previous.visible_tests
    assert case_fingerprint(case) != case_fingerprint(previous)

    public = prepare_case(case, tmp_path / "public")
    assert (public / "TASK.md").read_bytes() == case.description.read_bytes()
    assert not (public / "hidden_tests").exists()
    assert not list(public.rglob("*.patch"))
    assert not list(public.rglob("provenance.json"))


def test_precision_reference_and_mutant_calibrate_with_actual_tests(tmp_path):
    result = validate_case(precision_case(), tmp_path / "validation")
    assert result["status"] == "valid", result
    assert result["system_error"] is False
    assert result["baseline"]["outcomes"][LONG_NODE] == "failed"
    assert result["reference"]["status"] == "passed"
    assert result["reference"]["hidden"]["outcomes"][LONG_NODE] == "passed"
    assert result["mutant"]["status"] == "hidden_failed"
    assert result["mutant"]["visible"]["passed"] is True
    assert result["mutant"]["hidden"]["outcomes"][LONG_NODE] == "failed"


def test_legacy_reference_is_rejected_by_new_precision_acceptance(tmp_path):
    case = precision_case()
    previous = next(c for c in load_cases(ORIGINAL) if c.id == "case_15")
    result = grade_patch(case, previous.gold_patch.read_text("utf-8"), tmp_path / "legacy")
    assert result["status"] == "hidden_failed", result
    assert result["visible"]["passed"] is True
    assert result["hidden"]["outcomes"][LONG_NODE] == "failed"
