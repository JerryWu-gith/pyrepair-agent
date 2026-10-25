"""Actual owned grading must honor the frozen complete core node collection."""

import pytest

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.layered_grading import grade_layered, validate_layered_grade
from tests.evaluation_helpers import make_case


def collection(case):
    return {
        stage: sorted(
            n for n in case.fail_to_pass + case.pass_to_pass if n.partition("::")[0] in paths
        )
        for stage, paths in (("visible", case.visible_tests), ("hidden", case.hidden_tests))
    }


def test_lost_frozen_core_node_is_rejected_even_when_required_subset_passed(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    output = tmp_path / "grade"
    result = grade_layered(case, case.gold_patch.read_text(), output)
    expected = collection(case)
    expected["visible"].append("tests/test_app.py::test_existing_behavior")
    with pytest.raises(ValueError, match="core collection"):
        validate_layered_grade(result, output, frozen_case={"core_collection": expected})


def test_matching_complete_core_nodes_preserve_real_acceptance(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    output = tmp_path / "grade"
    result = grade_layered(case, case.gold_patch.read_text(), output)
    assert (
        validate_layered_grade(result, output, frozen_case={"core_collection": collection(case)})[
            "core_passed"
        ]
        is True
    )


def test_visible_failure_is_ordinary_failure_without_requiring_hidden_run(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    output = tmp_path / "grade"
    patch = case.gold_patch.read_text().replace("+    return a + b", "+    return a * b")
    result = grade_layered(case, patch, output)
    checked = validate_layered_grade(
        result, output, frozen_case={"core_collection": collection(case)}
    )
    assert checked["core"]["status"] == "visible_failed"
