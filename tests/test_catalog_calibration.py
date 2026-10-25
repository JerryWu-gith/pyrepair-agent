"""Audit saved report data and real asset fingerprints; never execute a task."""

import copy
import importlib
import importlib.util
import json
from dataclasses import replace

import pytest

from benchmarks.evaluation.cases import case_fingerprint, load_cases
from tests.evaluation_helpers import make_case

ENVIRONMENT = "a" * 64


def api():
    name = "benchmarks.evaluation.catalog_calibration"
    assert importlib.util.find_spec(name) is not None, "calibration index missing"
    return importlib.import_module(name)


def owned_report(tmp_path):
    case = replace(load_cases(make_case(tmp_path / "assets"))[0], source_kind="opensource")
    public, hidden = case.fail_to_pass
    regression = case.pass_to_pass[0]

    def stage(outcomes, *, failed):
        return {
            "backend": "docker",
            "started": True,
            "cleanup_errors": [],
            "identity": {"environment_hash": ENVIRONMENT},
            "integrity": {
                "before": {"owned.py": "b" * 64},
                "after": {"owned.py": "b" * 64},
                "unchanged": True,
            },
            "status": "failed" if failed else "passed",
            "passed": not failed,
            "returncode": 1 if failed else 0,
            "outcomes": outcomes,
            "assertion_failures": [n for n, value in outcomes.items() if value == "failed"],
            "skipped": [],
            "collection_errors": [],
        }

    report = {
        "case_id": case.id,
        "fingerprint": case_fingerprint(case),
        "status": "valid",
        "system_error": False,
        "baseline": stage({public: "failed", hidden: "failed", regression: "passed"}, failed=True),
        "reference": {
            "status": "passed",
            "visible": stage({public: "passed"}, failed=False),
            "hidden": stage({hidden: "passed", regression: "passed"}, failed=False),
        },
        "mutant": {
            "status": "hidden_failed",
            "visible": stage({public: "passed"}, failed=False),
            "hidden": stage({hidden: "failed", regression: "passed"}, failed=True),
        },
    }
    root = tmp_path / "calibration"
    (root / case.id).mkdir(parents=True)
    (root / case.id / "validation.json").write_text(json.dumps(report), encoding="utf-8")
    return case, root, report


def save(root, case, report):
    (root / case.id).mkdir(parents=True, exist_ok=True)
    (root / case.id / "validation.json").write_text(json.dumps(report), encoding="utf-8")


def test_index_binds_task_environment_and_saved_report_bytes(tmp_path):
    case, root, _report = owned_report(tmp_path)
    result = api().collect_calibrations([case], [root], ENVIRONMENT)
    assert result["status"] == "calibrations_verified"
    assert result["case_count"] == 1
    assert result["ready_for_model_evaluation"] is False
    row = result["cases"][0]
    assert row["fingerprint"] == case_fingerprint(case)
    assert row["environment_hash"] == ENVIRONMENT
    assert row["validation_path"] == str((root / case.id / "validation.json").resolve())
    assert len(row["validation_sha256"]) == 64


@pytest.mark.parametrize(
    "problem", ["environment", "assertions", "mutant", "cleanup", "changed_asset", "missing"]
)
def test_invalid_evidence_cannot_be_reused_for_final_assets(tmp_path, problem):
    case, root, report = owned_report(tmp_path)
    if problem == "environment":
        report["reference"]["hidden"]["identity"]["environment_hash"] = "c" * 64
    elif problem == "assertions":
        report["baseline"]["assertion_failures"] = []
    elif problem == "mutant":
        report["mutant"]["hidden"]["outcomes"] = {
            n: "passed" for n in report["mutant"]["hidden"]["outcomes"]
        }
    elif problem == "cleanup":
        report["mutant"]["hidden"]["cleanup_errors"] = ["container removal failed"]
    elif problem == "changed_asset":
        case.description.write_text("changed public contract", encoding="utf-8")
    else:
        root = tmp_path / "missing"
        root.mkdir()
    if problem != "missing":
        save(root, case, report)
    with pytest.raises(ValueError):
        api().collect_calibrations([case], [root], ENVIRONMENT)


def test_old_revision_is_retained_but_conflicting_same_revision_is_rejected(tmp_path):
    case, root, report = owned_report(tmp_path)
    other = tmp_path / "earlier"
    older = copy.deepcopy(report)
    older["fingerprint"] = "d" * 64
    older["status"] = "invalid_task"
    save(other, case, older)
    assert api().collect_calibrations([case], [other, root], ENVIRONMENT)["case_count"] == 1
    older["fingerprint"] = report["fingerprint"]
    save(other, case, older)
    with pytest.raises(ValueError, match="conflicting"):
        api().collect_calibrations([case], [other, root], ENVIRONMENT)


def test_synthetic_exception_contract_requires_explicit_docker_audit_opt_in(tmp_path):
    case, root, report = owned_report(tmp_path)
    case = replace(case, source_kind="synthetic")
    report["fingerprint"] = case_fingerprint(case)
    # Owned synthetic contracts may verify exception translation, not only asserts.
    report["baseline"]["assertion_failures"] = []
    report["mutant"]["hidden"]["assertion_failures"] = []
    save(root, case, report)
    with pytest.raises(ValueError):
        api().collect_calibrations([case], [root], ENVIRONMENT)
    assert (
        api().collect_calibrations([case], [root], ENVIRONMENT, include_synthetic=True)[
            "case_count"
        ]
        == 1
    )


def test_legacy_synthetic_extra_passing_collection_is_retained_not_dropped(tmp_path):
    case, root, report = owned_report(tmp_path)
    case = replace(case, source_kind="synthetic")
    report["fingerprint"] = case_fingerprint(case)
    extra = "tests/test_app.py::test_existing_behavior"
    report["baseline"]["outcomes"][extra] = "passed"
    report["reference"]["visible"]["outcomes"][extra] = "passed"
    report["mutant"]["visible"]["outcomes"][extra] = "passed"
    save(root, case, report)
    result = api().collect_calibrations([case], [root], ENVIRONMENT, include_synthetic=True)
    assert extra in result["cases"][0]["core_collection"]["visible"]
    assert result["cases"][0]["additional_passing_nodes"] == [extra]
    report["mutant"]["visible"]["outcomes"].pop(extra)
    save(root, case, report)
    with pytest.raises(ValueError):
        api().collect_calibrations([case], [root], ENVIRONMENT, include_synthetic=True)
