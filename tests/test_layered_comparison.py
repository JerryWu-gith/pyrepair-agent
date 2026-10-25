import json

import pytest

from benchmarks.evaluation.comparison_journal import run_slots
from benchmarks.evaluation.experiment import digest
from tests.test_comparison_journal import candidate, owned_pack
from tests.test_layered_grading import owned_case


def v2_pack(case=None):
    pack = owned_pack()
    pack["identity"].update(version=2)
    pack["identity"]["cases"][0]["regression_hash"] = "owned-scope"
    if case is not None:
        from benchmarks.evaluation.cases import case_fingerprint
        from benchmarks.evaluation.layered_assets import load_regression

        scope = load_regression(case)
        pack["identity"]["cases"][0].update(
            fingerprint=case_fingerprint(case),
            regression_hash=digest(scope),
            collection_hash=digest(sorted(scope["required"])),
        )
    pack["identity_hash"] = digest(pack["identity"])
    return pack


def test_safe_extended_timeout_continues_and_report_is_not_full_success(tmp_path):
    from benchmarks.evaluation.comparison_reporting import render_comparison, summarize_comparison
    from benchmarks.evaluation.grading import run_tests
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)

    def executor(slot, folder):
        return {**candidate(slot, folder), "patch": case.gold_patch.read_text("utf-8")}

    def runner(repo, paths, log, timeout, required=()):
        if paths == ("tests/test_extended.py",):
            return {"status": "timeout", "passed": False, "returncode": None, "outcomes": {}}
        return run_tests(repo, paths, log, timeout, required)

    def grader(slot, result, folder):
        return grade_layered(case, result["patch"], folder, test_runner=runner)

    records = run_slots(v2_pack(case), tmp_path / "run", executor, grader)
    assert len(records) == 2
    assert all(r["core_passed"] is True and r["fully_verified"] is False for r in records)
    summary = summarize_comparison(v2_pack(case), records)
    assert all(g["core_acceptance_rate"] == 1 for g in summary["groups"])
    assert summary["extended"]["timeout"] == 2
    assert summary["extended"]["fully_verified"] == 0
    assert "success_rate" not in summary["groups"][0]
    text = render_comparison(summary)
    assert "Core acceptance" in text and "Extended regression" in text
    phase = tmp_path / "run/s0000/g/core-grade.json"
    assert phase.exists()
    phase.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact"):
        run_slots(v2_pack(case), tmp_path / "run", executor, grader)


def test_journal_resume_reuses_the_same_grading_directory(tmp_path):
    from benchmarks.evaluation.grading import run_tests
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)
    folders = []

    def executor(slot, folder):
        return {**candidate(slot, folder), "patch": case.gold_patch.read_text("utf-8")}

    def interrupt(repo, paths, log, timeout, required=()):
        if paths == ("tests/test_extended.py",):
            raise KeyboardInterrupt
        return run_tests(repo, paths, log, timeout, required)

    def initial(slot, result, folder):
        folders.append(folder)
        return grade_layered(case, result["patch"], folder, test_runner=interrupt)

    root = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt):
        run_slots(v2_pack(case), root, executor, initial)

    def forbidden(*args, **kwargs):
        pytest.fail("resume must not call model or repeat stage")

    def resume(slot, result, folder):
        folders.append(folder)
        return grade_layered(case, result["patch"], folder, test_runner=forbidden)

    records = run_slots(v2_pack(case), root, forbidden, resume)
    assert folders[0] == folders[1] == root / "s0000/g"
    assert records[0]["core_passed"] is True
    assert records[0]["status"] == "technical_error"
    assert records[0]["grade"]["extended"]["status"] == "interrupted"


def test_v2_simulation_never_has_a_real_acceptance_rate(tmp_path):
    from benchmarks.evaluation.comparison_reporting import summarize_comparison
    from benchmarks.evaluation.layered_grading import simulated_grade

    pack = v2_pack()
    records = run_slots(
        pack, tmp_path / "run", candidate, lambda *args: simulated_grade(), simulation=True
    )
    summary = summarize_comparison(pack, records, simulation=True)
    assert summary["real_model_trials"] == 0
    assert all(g["core_acceptance_rate"] is None for g in summary["groups"])
    assert summary["extended"]["fully_verified"] is None


def test_pack_freezes_regression_scope_and_individual_calibration_artifacts(tmp_path, monkeypatch):
    from tests.test_comparison_pack import make_prepared

    def configure(pack, cases, lock):
        row = {
            "id": "demo",
            "revision": 1,
            "paths": ["tests/test_app.py"],
            "required": ["tests/test_app.py::test_add"],
            "core_repeats": 3,
            "timeout_seconds": 15,
            "reason": "owned",
        }
        (cases[0].root / "regression_opensource_v3.json").write_text(
            json.dumps({"version": 1, "cases": [row]}), encoding="utf-8"
        )

        def calibration(case, output, **kwargs):
            output.mkdir(parents=True)
            (output / "evidence.json").write_text('{"owned":1}', encoding="utf-8")
            return {
                "status": "valid",
                "extended": {"expected_nodes": ["tests/test_app.py::test_add"]},
            }

        monkeypatch.setattr(pack, "validate_layered", calibration, raising=False)

    pack, cases, output, _ = make_prepared(tmp_path, monkeypatch, configure)
    identity = pack.verify_pack(output, cases)["identity"]
    assert identity["version"] == 2
    assert identity["cases"][0]["regression_hash"] is not None
    path = output / "control/c00/v/evidence.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="calibration"):
        pack.verify_pack(output, cases)


def test_saved_foreign_patch_grade_is_rejected_in_journal_resume(tmp_path):
    from benchmarks.evaluation.comparison_budget import write_new
    from benchmarks.evaluation.grading import run_tests
    from benchmarks.evaluation.layered_grading import grade_layered

    case = owned_case(tmp_path)
    pack = v2_pack(case)
    pack["identity"]["slots"] = pack["identity"]["slots"][:1]
    pack["identity_hash"] = digest(pack["identity"])
    root = tmp_path / "run"

    def executor(slot, folder):
        return {**candidate(slot, folder), "patch": case.wrong_patch.read_text("utf-8")}

    def interrupted(*args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_slots(pack, root, executor, interrupted)
    successful_foreign = grade_layered(
        case, case.gold_patch.read_text("utf-8"), root / "s0000/g", test_runner=run_tests
    )
    write_new(root / "s0000/grade.json", successful_foreign)

    def forbidden(*args):
        pytest.fail("resume must not reexecute model or grader")

    records = run_slots(pack, root, forbidden, forbidden)
    assert records[0]["status"] == "technical_error"
    assert records[0].get("core_passed") is not True


def test_pack_cannot_freeze_an_extended_scope_without_complete_collection(tmp_path, monkeypatch):
    from tests.test_comparison_pack import make_prepared

    def configure(pack, cases, lock):
        (cases[0].root / "regression_opensource_v3.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": [
                        {
                            "id": "demo",
                            "revision": 1,
                            "paths": ["tests/test_app.py"],
                            "required": ["tests/test_app.py::test_add"],
                            "core_repeats": 3,
                            "timeout_seconds": 15,
                            "reason": "owned",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        def missing(case, output, **kwargs):
            output.mkdir(parents=True)
            return {"status": "valid", "extended": {"expected_nodes": []}}

        monkeypatch.setattr(pack, "validate_layered", missing)

    with pytest.raises(ValueError, match="collection"):
        make_prepared(tmp_path, monkeypatch, configure)
    assert not (tmp_path / "pack/pack.json").exists()


def test_120_maximum_size_candidates_keep_a_resumable_compact_journal(tmp_path):
    from benchmarks.evaluation.layered_grading import simulated_grade

    pack = owned_pack(20, 3)
    pack["identity"]["version"] = 2
    pack["identity_hash"] = digest(pack["identity"])
    root = tmp_path / "run"

    def large(slot, folder):
        return {**candidate(slot, folder), "patch": "x" * 256000}

    records = run_slots(pack, root, large, lambda *args: simulated_grade(), simulation=True)
    assert len(records) == 120
    assert (root / "journal.jsonl").stat().st_size < 2 * 1024 * 1024
    assert len(json.loads((root / "s0000/candidate.json").read_text("utf-8"))["patch"]) == 256000

    def forbidden(*args):
        pytest.fail("complete simulation must not execute again")

    assert run_slots(pack, root, forbidden, forbidden, simulation=True) == records
