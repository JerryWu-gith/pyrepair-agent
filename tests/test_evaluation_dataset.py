from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.evaluation.cases import load_cases
from tests.evaluation_helpers import make_case


def test_task_preflight_checks_buggy_gold_and_overfit_patch(tmp_path):
    from benchmarks.evaluation.grading import validate_case

    case = load_cases(make_case(tmp_path / "bank"))[0]
    result = validate_case(case, tmp_path / "validation")
    assert result["status"] == "valid"
    assert result["baseline"]["outcomes"]["tests/test_app.py::test_add"] == "failed"
    assert result["reference"]["status"] == "passed"
    assert result["mutant"]["status"] == "hidden_failed"


@pytest.mark.parametrize("defect", ["bad_reference", "weak_hidden", "fixed_baseline", "bad_p2p"])
def test_bad_task_never_becomes_an_evaluation_case(tmp_path, defect):
    from benchmarks.evaluation.grading import validate_case

    case = load_cases(make_case(tmp_path / "bank"))[0]
    if defect == "bad_reference":
        case.gold_patch.write_bytes(case.wrong_patch.read_bytes())
    elif defect == "weak_hidden":
        case.wrong_patch.write_bytes(case.gold_patch.read_bytes())
    elif defect == "fixed_baseline":
        (case.buggy / "src/app.py").write_text("def add(a,b): return a+b\n")
    else:
        case = replace(case, pass_to_pass=("tests/test_app.py::test_add",))
    assert validate_case(case, tmp_path / "validation")["status"] == "invalid_task"


def test_committed_development_bank_has_18_valid_tasks(tmp_path):
    from benchmarks.evaluation.grading import validate_case

    manifest = Path(__file__).resolve().parents[1] / "benchmarks/manifest_v2.json"
    cases = load_cases(manifest)
    assert len(cases) == 18
    assert {c.split for c in cases} == {"dev"}
    assert {c.source_kind for c in cases} == {"synthetic"}
    multi = []
    for case in cases:
        result = validate_case(case, tmp_path / case.id)
        assert result["status"] == "valid", (case.id, result)
        if case.suite == "capability":
            multi.append(result)
    assert len(multi) == 3
    assert all(len(r["reference"]["changed_files"]) >= 2 for r in multi)
