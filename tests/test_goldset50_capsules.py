"""Saved calibration reuse must preserve real identity, never just a valid label."""

import importlib
import importlib.util

import pytest

from benchmarks.evaluation.catalog_calibration import collect_calibrations
from tests.test_catalog_calibration import ENVIRONMENT, owned_report


def api():
    name = "benchmarks.evaluation.goldset_pack"
    assert importlib.util.find_spec(name) is not None, "goldset pack missing"
    return importlib.import_module(name)


def test_portable_capsule_contains_exact_source_evidence_and_identity(tmp_path):
    case, root, _report = owned_report(tmp_path)
    index = collect_calibrations([case], [root], ENVIRONMENT)
    reuse = api().calibration_reuser(index)
    output = tmp_path / "capsule"
    result = reuse(case, output, {"verified_hash": ENVIRONMENT})
    assert result["status"] == "valid"
    assert result["core"][0]["fingerprint"] == index["cases"][0]["fingerprint"]
    assert (output / "raw-validation.json").read_bytes() == (
        root / case.id / "validation.json"
    ).read_bytes()
    assert not list(output.rglob("*.py"))
    assert not (output / "repo").exists()
    with pytest.raises(FileExistsError):
        reuse(case, output, {"verified_hash": ENVIRONMENT})


@pytest.mark.parametrize("problem", ["source", "case", "environment"])
def test_capsule_refuses_evidence_or_task_drift(tmp_path, problem):
    case, root, _report = owned_report(tmp_path)
    index = collect_calibrations([case], [root], ENVIRONMENT)
    reuse = api().calibration_reuser(index)
    environment = ENVIRONMENT
    if problem == "source":
        with (root / case.id / "validation.json").open("a") as stream:
            stream.write(" ")
    elif problem == "case":
        case.description.write_text("changed contract")
    else:
        environment = "c" * 64
    with pytest.raises(ValueError):
        reuse(case, tmp_path / "capsule", {"verified_hash": environment})
    assert not (tmp_path / "capsule").exists()


def test_pack_output_alias_is_rejected_before_environment_or_case_reads(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    module = api()
    monkeypatch.setattr(
        module, "verify_dataset", lambda *a: pytest.fail("must reject overlap first")
    )
    with pytest.raises(ValueError, match="overlap"):
        module.prepare_goldset_pack(
            dataset, sibling / ".." / "dataset" / "nested", tmp_path / "lock.json", []
        )
