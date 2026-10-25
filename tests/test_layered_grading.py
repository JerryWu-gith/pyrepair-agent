"""Owned small repositories exercise actual patch/core grading; no upstream host execution."""

import json

import pytest

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.grading import run_tests
from tests.evaluation_helpers import make_case


def owned_case(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    (case.buggy / "tests/test_extended.py").write_text(
        "from app import add\ndef test_extended():\n    assert add(-2, 1) == -1\n", encoding="utf-8"
    )
    (case.root / "regression_opensource_v3.json").write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "id": case.id,
                        "revision": case.revision,
                        "paths": ["tests/test_extended.py"],
                        "required": ["tests/test_extended.py::test_extended"],
                        "timeout_seconds": 15,
                        "core_repeats": 3,
                        "reason": "Owned regression boundary",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return case


def test_correct_patch_has_independent_core_and_public_only_extended_acceptance(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered, validate_layered_grade

    case = owned_case(tmp_path)

    def runner(repo, paths, log, timeout, required=()):
        if paths == ("tests/test_extended.py",):
            assert not (repo / "hidden_tests").exists()
        return run_tests(repo, paths, log, timeout, required)

    result = grade_layered(
        case, case.gold_patch.read_text("utf-8"), tmp_path / "g", test_runner=runner
    )
    assert result["core_passed"] is True
    assert result["status"] == "core_passed"
    assert result["extended"]["status"] == "passed"
    assert result["fully_verified"] is True
    validate_layered_grade(result, tmp_path / "g")


@pytest.mark.parametrize("status", ["timeout", "failed", "environment_error"])
def test_extension_outcome_never_erases_core_or_becomes_fully_verified(tmp_path, status):
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)

    def runner(repo, paths, log, timeout, required=()):
        if paths == ("tests/test_extended.py",):
            return {
                "status": status,
                "passed": False,
                "returncode": 1 if status == "failed" else None,
                "outcomes": {required[0]: "failed"} if status == "failed" else {},
            }
        return run_tests(repo, paths, log, timeout, required)

    result = grade_layered(
        case, case.gold_patch.read_text("utf-8"), tmp_path / "g", test_runner=runner
    )
    assert result["core_passed"] is True
    assert result["extended"]["status"] == status
    assert result["fully_verified"] is False
    assert result["status"] == (
        "environment_error" if status == "environment_error" else "core_passed"
    )


def test_core_failure_does_not_run_extended_or_report_success(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)

    def runner(repo, paths, log, timeout, required=()):
        assert paths != ("tests/test_extended.py",)
        return run_tests(repo, paths, log, timeout, required)

    result = grade_layered(
        case, case.wrong_patch.read_text("utf-8"), tmp_path / "g", test_runner=runner
    )
    assert result["core_passed"] is False
    assert result["status"] == "hidden_failed"
    assert result["extended"]["status"] == "not_run_core_failed"


def test_interrupted_extension_recovers_saved_core_without_reexecuting_either_stage(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)

    def interrupted(repo, paths, log, timeout, required=()):
        if paths == ("tests/test_extended.py",):
            raise KeyboardInterrupt
        return run_tests(repo, paths, log, timeout, required)

    output = tmp_path / "g"
    patch = case.gold_patch.read_text("utf-8")
    with pytest.raises(KeyboardInterrupt):
        grade_layered(case, patch, output, test_runner=interrupted)
    assert json.loads((output / "core-grade.json").read_text("utf-8"))["status"] == "passed"

    def forbidden(*args, **kwargs):
        pytest.fail("an already started stage must not run again")

    result = grade_layered(case, patch, output, test_runner=forbidden)
    assert result["core_passed"] is True
    assert result["extended"]["status"] == "interrupted"
    assert result["fully_verified"] is False


def test_modified_saved_core_cannot_resume_as_accepted(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)
    output = tmp_path / "g"
    patch = case.gold_patch.read_text("utf-8")
    grade_layered(case, patch, output, test_runner=run_tests)
    path = output / "core-grade.json"
    value = json.loads(path.read_text("utf-8"))
    value["status"] = "hidden_failed"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact"):
        grade_layered(case, patch, output, test_runner=run_tests)


def test_calibration_requires_three_valid_core_runs_and_checks_reference_extension(tmp_path):
    from benchmarks.evaluation.layered_grading import validate_layered

    case = owned_case(tmp_path)
    result = validate_layered(case, tmp_path / "v", test_runner=run_tests)
    assert result["status"] == "valid"
    assert len(result["core"]) == 3
    assert result["extended"]["baseline"]["status"] == "failed"
    assert result["extended"]["reference"]["status"] == "passed"
    assert len(result["evidence"]) == 5


def test_failed_calibration_is_retained_not_retried_until_valid(tmp_path):
    from benchmarks.evaluation.layered_grading import validate_layered

    case = owned_case(tmp_path)

    def invalid(case, output, **kwargs):
        output.mkdir(parents=True)
        return {"status": "invalid_task"}

    result = validate_layered(case, tmp_path / "v", test_runner=run_tests, core_validator=invalid)
    assert result["status"] == "invalid_task"
    assert len(result["core"]) == 1
    assert result["extended"] is None
    assert not (tmp_path / "v/c1").exists()


def test_journal_grade_is_compact_but_full_extension_evidence_is_retained(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)

    def runner(repo, paths, log, timeout, required=()):
        result = run_tests(repo, paths, log, timeout, required)
        if paths == ("tests/test_extended.py",):
            result["owned_diagnostic"] = "x" * 20000
        return result

    output = tmp_path / "g"
    result = grade_layered(case, case.gold_patch.read_text("utf-8"), output, test_runner=runner)
    assert result["extended"] == {"status": "passed"}
    assert len(json.dumps(result)) < 2000
    raw = json.loads((output / "extended-regression.json").read_text("utf-8"))
    assert len(raw["stage"]["owned_diagnostic"]) == 20000


def test_saved_grade_requires_actual_booleans_not_integer_aliases(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered, validate_layered_grade

    case = owned_case(tmp_path)
    result = grade_layered(
        case, case.gold_patch.read_text("utf-8"), tmp_path / "g", test_runner=run_tests
    )
    result["core_passed"] = 1
    with pytest.raises(ValueError):
        validate_layered_grade(result)


def test_extension_controller_exception_keeps_known_core_acceptance(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)

    def runner(repo, paths, log, timeout, required=()):
        if paths == ("tests/test_extended.py",):
            raise OSError("owned extension boundary failure")
        return run_tests(repo, paths, log, timeout, required)

    result = grade_layered(
        case, case.gold_patch.read_text("utf-8"), tmp_path / "g", test_runner=runner
    )
    assert result["core_passed"] is True
    assert result["status"] == "environment_error"
    assert result["extended"]["status"] == "environment_error"


def test_missing_frozen_extension_node_is_not_a_passing_regression(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)

    def runner(repo, paths, log, timeout, required=()):
        if paths == ("tests/test_extended.py",):
            return {
                "status": "passed",
                "passed": True,
                "returncode": 0,
                "outcomes": {"tests/test_extended.py::test_extended": "passed"},
            }
        return run_tests(repo, paths, log, timeout, required)

    result = grade_layered(
        case,
        case.gold_patch.read_text("utf-8"),
        tmp_path / "g",
        test_runner=runner,
        expected_nodes=[
            "tests/test_extended.py::test_extended",
            "tests/test_extended.py::test_other",
        ],
    )
    assert result["core_passed"] is True
    assert result["status"] == "grader_error"


def test_grade_identity_is_bound_to_candidate_patch_and_frozen_task(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered, validate_layered_grade

    case = owned_case(tmp_path)
    patch = case.gold_patch.read_text("utf-8")
    output = tmp_path / "g"
    result = grade_layered(case, patch, output, test_runner=run_tests)
    with pytest.raises(ValueError, match="identity"):
        validate_layered_grade(result, output, candidate_patch=case.wrong_patch.read_text("utf-8"))


def test_large_raw_evidence_is_saved_separately_from_compact_calibration(tmp_path):
    from benchmarks.evaluation.layered_grading import grade_layered, validate_layered

    case = owned_case(tmp_path)

    def runner(repo, paths, log, timeout, required=()):
        result = run_tests(repo, paths, log, timeout, required)
        if paths == ("tests/test_extended.py",):
            result["owned_diagnostic"] = "x" * (4 * 1024 * 1024 + 1)
        return result

    calibrated = validate_layered(case, tmp_path / "v", test_runner=runner)
    assert calibrated["status"] == "valid"
    assert (tmp_path / "v/calibration.json").stat().st_size < 100000
    assert (tmp_path / "v/r/extended-result.json").stat().st_size > 4 * 1024 * 1024
    result = grade_layered(
        case, case.gold_patch.read_text("utf-8"), tmp_path / "g", test_runner=runner
    )
    assert result["fully_verified"] is True
    assert (tmp_path / "g/extended-regression.json").stat().st_size > 4 * 1024 * 1024
