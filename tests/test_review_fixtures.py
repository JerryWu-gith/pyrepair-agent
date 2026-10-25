import json
from pathlib import Path

import pytest

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.grading import run_tests
from benchmarks.evaluation.patching import apply_patch_checked
from tests.evaluation_helpers import make_case

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks/review_cases"


def test_money_calibration_passes_boundaries_that_historical_candidate_fails(tmp_path):
    from benchmarks.evaluation.cases import prepare_case

    case = next(c for c in load_cases(ROOT / "benchmarks/manifest_v2.json") if c.id == "case_15")
    for name, want in [
        ("case_15_positive.patch", "passed"),
        ("diagnostics/case_15_historical.patch", "failed"),
    ]:
        repo = prepare_case(case, tmp_path / want)
        apply_patch_checked(case, repo, (FIXTURES / name).read_text(encoding="utf-8"))
        target = repo / "precision_tests/test_money_precision.py"
        target.parent.mkdir()
        target.write_bytes((FIXTURES / "precision_tests/test_money_precision.py").read_bytes())
        result = run_tests(
            repo, ("precision_tests/test_money_precision.py",), tmp_path / (want + ".log"), 15
        )
        assert result["status"] == want
        assert len(result["outcomes"]) == 18
        assert set(result["outcomes"].values()) <= {"passed", "failed"}


def mini_fixtures(tmp_path):
    manifest = make_case(tmp_path / "bank")
    case = load_cases(manifest)[0]
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    rows = []
    for label, source in [(True, case.gold_patch), (False, case.wrong_patch)]:
        name = "positive" if label else "negative"
        (fixtures / (name + ".patch")).write_bytes(source.read_bytes())
        rows.append(
            {
                "id": name,
                "case_id": "demo",
                "patch": name + ".patch",
                "expected_approved": label,
                "source": {"kind": "test_fixture", "note": "PRIVATE_LABEL_CANARY"},
                "basis": "Return sum; constant five violates add(3,4).",
            }
        )
    (fixtures / "manifest.json").write_text(
        json.dumps({"version": 1, "candidates": rows}), encoding="utf-8"
    )
    return manifest, fixtures


def test_prepare_validates_labels_freezes_public_inputs_and_rejects_tampering(tmp_path):
    from benchmarks.evaluation.review_fixtures import load_prepared, prepare_review

    manifest, fixtures = mini_fixtures(tmp_path)
    out = prepare_review(manifest, fixtures, tmp_path / "prepared")
    data = load_prepared(out)
    assert len(data["inputs"]) == 2
    assert data["labels"] == {"positive": True, "negative": False}
    assert data["grading"]["positive"]["status"] == "passed"
    assert data["grading"]["negative"]["status"] == "hidden_failed"
    public = json.dumps(data["inputs"])
    assert "PRIVATE_LABEL_CANARY" not in public
    assert "hidden_tests" not in public
    assert "gold.patch" not in public
    assert "Return the sum" in public
    with pytest.raises(FileExistsError):
        prepare_review(manifest, fixtures, out)
    path = out / "prepared.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["payload"]["labels"]["positive"] = False
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        load_prepared(out)


def test_prepare_refuses_mislabeled_candidate(tmp_path):
    from benchmarks.evaluation.review_fixtures import prepare_review

    manifest, fixtures = mini_fixtures(tmp_path)
    path = fixtures / "manifest.json"
    saved = json.loads(path.read_text())
    saved["candidates"][1]["expected_approved"] = True
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="label"):
        prepare_review(manifest, fixtures, tmp_path / "prepared")
    assert not (tmp_path / "prepared/prepared.json").exists()


@pytest.mark.parametrize("defect", ["empty", "unknown_case", "duplicate", "missing_patch"])
def test_invalid_candidate_collection_never_emits_ready(tmp_path, defect):
    from benchmarks.evaluation.review_fixtures import prepare_review

    manifest, fixtures = mini_fixtures(tmp_path)
    path = fixtures / "manifest.json"
    definition = json.loads(path.read_text(encoding="utf-8"))
    if defect == "empty":
        definition["candidates"] = []
    elif defect == "unknown_case":
        definition["candidates"][0]["case_id"] = "unknown"
    elif defect == "duplicate":
        definition["candidates"].append(definition["candidates"][0])
    else:
        definition["candidates"][0]["patch"] = "missing.patch"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        prepare_review(manifest, fixtures, tmp_path / "prepared")
    assert not (tmp_path / "prepared/prepared.json").exists()


@pytest.mark.parametrize("defect", ["call_exception", "missing_required_node"])
def test_negative_label_needs_assertion_evidence_and_all_required_nodes(tmp_path, defect):
    from benchmarks.evaluation.review_fixtures import prepare_review
    from tests.evaluation_helpers import patch

    manifest, fixtures = mini_fixtures(tmp_path)
    case = load_cases(manifest)[0]
    if defect == "call_exception":
        old = (case.buggy / "src/app.py").read_text(encoding="utf-8")
        new = "def add(a, b):\n    if a == 3:\n        raise FileNotFoundError('missing data')\n    return 5\n"
        (fixtures / "negative.patch").write_text(patch(old, new), encoding="utf-8")
    else:
        hidden = case.private / "hidden_tests/test_hidden.py"
        hidden.write_text(
            "from app import add\n\ndef test_other():\n    assert add(3, 4) == 7\n",
            encoding="utf-8",
        )
        # Only prepare the negative candidate; a positive candidate would already
        # reject missing required nodes through the old grader's passed check.
        path = fixtures / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["candidates"] = [data["candidates"][1]]
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="label"):
        prepare_review(manifest, fixtures, tmp_path / "prepared")
    assert not (tmp_path / "prepared/prepared.json").exists()
