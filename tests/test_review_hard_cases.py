"""Real subprocess calibration of synthetic/dev fixed candidates; no model API."""

import json
from pathlib import Path

import pytest

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.grading import validate_case
from benchmarks.evaluation.review_fixtures import (
    _assertion_failure,
    load_prepared,
    prepare_review,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/manifest_review_hard_v1.json"
FIXTURES = ROOT / "benchmarks/review_cases_hard_v1"
IDS = ["case_04", "case_13", "case_15", "multi_orders", "multi_inventory", "multi_time"]


@pytest.fixture(scope="module")
def hard_prepared(tmp_path_factory):
    return prepare_review(MANIFEST, FIXTURES, tmp_path_factory.mktemp("hard") / "prepared")


def test_twelve_labels_have_real_visible_and_assertion_evidence(hard_prepared):
    data = load_prepared(hard_prepared)
    assert set(data["baselines"]) == set(IDS)
    assert len(data["inputs"]) == 12
    assert data["dataset"]["id"] == "review-hard-v1"
    assert set(data["dataset"]["candidate_cases"].values()) == set(IDS)
    for case_id in IDS:
        positive, negative = [f"hard_v1_{case_id}_{suffix}" for suffix in ("positive", "negative")]
        assert data["labels"][positive] is True
        assert data["labels"][negative] is False
        assert data["grading"][positive]["status"] == "passed"
        assert data["grading"][negative]["status"] == "hidden_failed"
        assert _assertion_failure(data["grading"][negative]["hidden"])
        for candidate in (positive, negative):
            assert data["grading"][candidate]["visible"]["passed"]
            hidden = data["grading"][candidate]["hidden"]
            assert set(hidden["required"]) == set(hidden["outcomes"])
        assert data["inputs"][positive]["failure"] == data["inputs"][negative]["failure"]
        assert _assertion_failure(data["baselines"][case_id])
    public = json.dumps(data["inputs"])
    assert "hidden_tests" not in public
    assert "gold.patch" not in public
    assert "expected_approved" not in public


@pytest.mark.parametrize("case_id", IDS)
def test_buggy_f2p_p2p_and_fixed_references_are_valid(case_id, tmp_path):
    case = next(c for c in load_cases(MANIFEST) if c.id == case_id)
    assert case.split == "dev" and case.source_kind == "synthetic"
    result = validate_case(case, tmp_path / case_id)
    assert result["status"] == "valid", result


def test_new_negative_mechanisms_have_named_counterexamples(hard_prepared):
    data = load_prepared(hard_prepared)
    failing_nodes = {
        "case_04": "test_contract",
        "case_13": "test_contract",
        "case_15": "test_exact_cents_independent_of_decimal_context[long-prec28]",
        "multi_orders": "test_total_rounding",
        "multi_inventory": "test_preserved",
        "multi_time": "test_parser_returns_utc",
    }
    for case_id, node in failing_nodes.items():
        negative = data["grading"][f"hard_v1_{case_id}_negative"]["hidden"]
        assert f"hidden_tests/test_acceptance.py::{node}" in negative["assertion_failures"]
