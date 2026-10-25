import json

import pytest

from benchmarks.evaluation.cases import load_cases
from tests.evaluation_helpers import make_case
from tests.test_comparison_evidence import OwnedRunner


def make_prepared(tmp_path, monkeypatch, before_prepare=None):
    from benchmarks.evaluation import comparison_pack as pack

    cases = load_cases(make_case(tmp_path / "assets"))
    lock = tmp_path / "environment-lock.json"
    lock.write_text('{"image_id":"owned-image"}', encoding="utf-8")
    lock.with_name("environment-check.json").write_text("{}", encoding="utf-8")

    class Backend:
        def __init__(self, lock):
            self.lock = lock

        def assert_environment_verified(self):
            return {"environment_hash": "owned-hash", "image_id": "owned-image"}

    monkeypatch.setattr(pack, "DockerTestRunner", Backend)
    monkeypatch.setattr(pack, "DockerAgentTestRunner", lambda *args: OwnedRunner())
    monkeypatch.setattr(pack, "validate_case", lambda *args, **kwargs: {"status": "valid"})
    monkeypatch.setattr(pack, "runtime_identity", lambda: {"source_hash": "owned-v1"})
    if before_prepare is not None:
        before_prepare(pack, cases, lock)
    output = pack.prepare_pack(cases, tmp_path / "pack", lock, "deepseek-flash", 3)
    return pack, cases, output, lock


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    return lambda: make_prepared(tmp_path, monkeypatch)


def test_frozen_pack_verifies_and_slots_are_paired_and_alternating(prepared):
    pack, cases, output, _ = prepared()
    value = pack.verify_pack(output, cases)
    assert len(value["identity"]["slots"]) == 6
    assert [s["method"] for s in value["identity"]["slots"]] == [
        "single-shot",
        "full-agent",
        "full-agent",
        "single-shot",
        "single-shot",
        "full-agent",
    ]
    assert value["identity"]["authorization"] == "offline-only"
    payload = json.loads((output / "p/c00/spec.json").read_text("utf-8"))
    assert set(payload) == {
        "version",
        "case_id",
        "revision",
        "source_kind",
        "visible_tests",
        "timeout_seconds",
        "input_policy",
        "public_input_hash",
    }


@pytest.mark.parametrize("asset", ["public", "evidence", "private", "lock", "pack"])
def test_tampering_is_rejected_before_a_model_could_be_constructed(prepared, asset):
    pack, cases, output, lock = prepared()
    paths = {
        "public": output / "p/c00/r/src/app.py",
        "evidence": output / "p/c00/evidence.json",
        "private": cases[0].gold_patch,
        "lock": lock,
        "pack": output / "pack.json",
    }
    with paths[asset].open("a", encoding="utf-8") as stream:
        stream.write("changed")
    with pytest.raises((ValueError, OSError)):
        pack.verify_pack(output, cases)


def test_runtime_change_refuses_resume(prepared, monkeypatch):
    pack, cases, output, _ = prepared()
    monkeypatch.setattr(pack, "runtime_identity", lambda: {"source_hash": "owned-v2"})
    with pytest.raises(ValueError, match="runtime"):
        pack.verify_pack(output, cases)


def test_existing_output_is_not_overwritten(prepared):
    pack, cases, output, lock = prepared()
    original = (output / "pack.json").read_bytes()
    with pytest.raises(FileExistsError):
        pack.prepare_pack(cases, output, lock, "deepseek-flash", 3)
    assert (output / "pack.json").read_bytes() == original


def test_20_tasks_three_trials_have_120_distinct_planned_slots():
    from benchmarks.evaluation.comparison_pack import paired_slots

    slots = paired_slots([f"case_{n:02d}" for n in range(20)], 3)
    assert len(slots) == len({s["slot"] for s in slots}) == 120
    assert sum(s["method"] == "single-shot" for s in slots) == 60


@pytest.mark.parametrize(
    "ids,trials", [([], 3), (["a", "a"], 3), (["../x"], 3), (["a"], True), (["a"], 0)]
)
def test_invalid_schedule_is_rejected(ids, trials):
    from benchmarks.evaluation.comparison_pack import paired_slots

    with pytest.raises(ValueError):
        paired_slots(ids, trials)


@pytest.mark.parametrize("drift", ["case", "runtime", "environment"])
def test_drift_during_preparation_never_finalizes_a_pack(tmp_path, monkeypatch, drift):
    def configure(pack, cases, lock):
        def changed(*args, **kwargs):
            if drift == "case":
                cases[0].description.write_text("changed during capture", encoding="utf-8")
            elif drift == "runtime":
                monkeypatch.setattr(pack, "runtime_identity", lambda: {"source_hash": "owned-v2"})
            else:
                with lock.open("a", encoding="utf-8") as stream:
                    stream.write(" ")
            return {"status": "valid"}

        monkeypatch.setattr(pack, "validate_case", changed)

    with pytest.raises(ValueError, match="changed"):
        make_prepared(tmp_path, monkeypatch, configure)
    assert not (tmp_path / "pack/pack.json").exists()
    assert (tmp_path / "pack/preparation-error.json").exists()
