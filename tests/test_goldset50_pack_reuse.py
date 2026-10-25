"""The shared pack can consume independently verified offline calibration capsules."""

import pytest

from tests.test_comparison_pack import make_prepared


def test_matching_capsule_is_frozen_without_reexecuting_calibration(tmp_path, monkeypatch):
    from benchmarks.evaluation.cases import case_fingerprint
    from benchmarks.evaluation.comparison_budget import write_new

    pack, cases, _old, lock = make_prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(
        pack, "validate_layered", lambda *a, **k: pytest.fail("must reuse calibration")
    )

    def reused(case, output, environment):
        output.mkdir(parents=True)
        write_new(
            output / "verified-source.json",
            {"fingerprint": case_fingerprint(case), "environment": environment},
        )
        return {"status": "valid"}

    output = pack.prepare_pack(
        cases, tmp_path / "reused", lock, "deepseek-flash", 3, calibration_reuser=reused
    )
    frozen = pack.verify_pack(output, cases)
    assert "verified-source.json" in frozen["identity"]["cases"][0]["calibration_artifacts"]
    assert (output / "control/c00/v/verified-source.json").is_file()


def test_invalid_reused_evidence_never_finalizes_pack(tmp_path, monkeypatch):
    pack, cases, _old, lock = make_prepared(tmp_path, monkeypatch)

    def invalid(case, output, environment):
        output.mkdir(parents=True)
        return {"status": "invalid_task"}

    output = tmp_path / "invalid-reuse"
    with pytest.raises(ValueError, match="preflight"):
        pack.prepare_pack(cases, output, lock, "deepseek-flash", 3, calibration_reuser=invalid)
    assert not (output / "pack.json").exists()
    assert (output / "preparation-error.json").exists()
