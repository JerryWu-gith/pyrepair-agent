"""Controller validation and pause/resume have no implicit paid authority."""

import copy
import json
from dataclasses import replace

import pytest

from tests.test_comparison_pack import make_prepared
from tests.test_live_plan import approval


def live_fixture(tmp_path, monkeypatch):
    def twenty(pack, cases, lock):
        base = cases[0]
        cases[:] = [replace(base, id=f"case_{n:02d}") for n in range(18)] + [
            replace(base, id="os_more_seekable_1269", revision=2, source_kind="opensource"),
            replace(base, id="os_boltons_addlist_458", revision=2, source_kind="opensource"),
        ]
        (base.root / "regression_opensource_v3.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": [
                        {
                            "id": "os_more_seekable_1269",
                            "revision": 2,
                            "paths": ["tests/test_app.py"],
                            "required": ["tests/test_app.py::test_add"],
                            "timeout_seconds": 15,
                            "core_repeats": 3,
                            "reason": "Owned control fixture",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        original = pack.validate_layered

        def calibration(case, output, **kwargs):
            if case.id != "os_more_seekable_1269":
                return original(case, output, **kwargs)
            output.mkdir(parents=True)
            return {
                "status": "valid",
                "extended": {"expected_nodes": ["tests/test_app.py::test_add"]},
            }

        monkeypatch.setattr(pack, "validate_layered", calibration)

    _, cases, path, _ = make_prepared(tmp_path, monkeypatch, twenty)
    return path, cases


def no_credential():
    pytest.fail("offline/invalid execution must not read a credential")


def test_offline_smoke_controller_exports_actual_scope_without_model_or_credential(
    tmp_path, monkeypatch
):
    from benchmarks.evaluation.live_comparison import execute_comparison, inspect_execution

    path, cases = live_fixture(tmp_path, monkeypatch)
    output = tmp_path / "smoke"
    plan = inspect_execution(path, cases, output, "smoke", 37)
    # Only bypass the external environment probe; no-patch grading never runs a container.
    monkeypatch.setattr(
        "benchmarks.evaluation.docker_runner.DockerTestRunner.assert_environment_verified",
        lambda self: {"environment_hash": "owned-hash", "image_id": "owned-image"},
    )

    def no_patch(job):
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    summary = execute_comparison(
        path,
        cases,
        output,
        "smoke",
        37,
        approval(plan),
        offline_executor=no_patch,
        credential_getter=no_credential,
    )

    saved = json.loads((output / "summary.json").read_text("utf-8"))
    report = (output / "report.md").read_text("utf-8")
    assert saved == summary
    assert summary["planned"] == summary["finished"] == 2
    assert summary["execution_mode"] == "smoke"
    assert summary["real_model_trials"] == 0
    assert all(group["core_acceptance_rate"] is None for group in summary["groups"])
    assert "1 task(s)" in report
    assert "scheduled trials per task: 1" in report
    assert "not a formal repeated evaluation" in report
    assert "three repeats" not in report


def test_inspect_verifies_pack_without_output_or_quota(tmp_path, monkeypatch):
    from benchmarks.evaluation.live_comparison import inspect_execution

    path, cases = live_fixture(tmp_path, monkeypatch)
    plan = inspect_execution(path, cases, tmp_path / "output", "formal", 2220)
    assert len(plan["slots"]) == 120
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "failure", ["missing", "model", "order", "quota", "output", "runtime", "evidence"]
)
def test_invalid_approval_or_pack_is_rejected_before_credential_and_output(
    tmp_path, monkeypatch, failure
):
    from benchmarks.evaluation.live_comparison import execute_comparison, inspect_execution

    path, cases = live_fixture(tmp_path, monkeypatch)
    output = tmp_path / "output"
    plan = inspect_execution(path, cases, output, "formal", 2220)
    value = approval(plan)
    if failure == "missing":
        value = None
    elif failure == "evidence":
        (path / "p/c00/evidence.json").write_text("{}", encoding="utf-8")
    else:
        changed = copy.deepcopy(plan)
        if failure == "model":
            changed["config"]["model"] = "other-model"
        elif failure == "order":
            changed["slots"].reverse()
        elif failure == "quota":
            changed["call_limit"] = 1
        elif failure == "output":
            changed["output"] = str(tmp_path / "elsewhere")
        else:
            changed["runtime"]["source_hash"] = "changed"
        value = approval(changed)
    with pytest.raises((ValueError, OSError)):
        execute_comparison(
            path, cases, output, "formal", 2220, value, credential_getter=no_credential
        )
    assert not output.exists()


def test_normal_failures_continue_technical_failure_pauses_and_resume_never_restarts(
    tmp_path, monkeypatch
):
    from benchmarks.evaluation.live_comparison import execute_comparison, inspect_execution

    path, cases = live_fixture(tmp_path, monkeypatch)
    output = tmp_path / "output"
    plan = inspect_execution(path, cases, output, "formal", 2220)
    value = approval(plan)
    calls = []

    def owned_executor(job):
        calls.append(job["slot"]["slot"])
        if len(calls) == 3:
            raise RuntimeError("owned infrastructure failure")
        return {
            "status": "no_patch",
            "patch": "",
            "internal_success": None,
            "duration_seconds": 0.1,
        }

    result = execute_comparison(
        path,
        cases,
        output,
        "formal",
        2220,
        value,
        offline_executor=owned_executor,
        credential_getter=no_credential,
    )
    assert calls == ["case_00--1--single-shot", "case_00--1--full-agent", "case_00--2--full-agent"]
    assert result["planned"] == 120
    assert result["finished"] == 3
    assert result["unrun"] == 117
    assert result["real_model_trials"] == 0
    assert all(g["core_acceptance_rate"] is None for g in result["groups"])
    before = (output / "journal.jsonl").read_bytes()

    def forbidden(job):
        pytest.fail("technical terminal cannot be refilled")

    again = execute_comparison(
        path,
        cases,
        output,
        "formal",
        2220,
        value,
        resume=True,
        offline_executor=forbidden,
        credential_getter=no_credential,
    )
    assert again == result
    assert (output / "journal.jsonl").read_bytes() == before
    with pytest.raises(FileExistsError):
        execute_comparison(
            path, cases, output, "formal", 2220, value, credential_getter=no_credential
        )


def test_default_inspect_cli_has_no_execution_side_effects(tmp_path, monkeypatch, capsys):
    from benchmarks import run_live_comparison as cli

    path, cases = live_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "load_cases", lambda manifest: cases)
    output = tmp_path / "output"
    result = cli.main(
        [
            "--pack",
            str(path),
            "--output",
            str(output),
            "--mode",
            "smoke",
            "--call-limit",
            "37",
            "--manifest",
            "owned",
        ]
    )
    assert result == 0
    assert "NOT AUTHORIZED" in capsys.readouterr().out
    assert not output.exists()


def test_second_verification_cannot_rebind_a_different_valid_pack_to_old_approval(
    tmp_path, monkeypatch
):
    from benchmarks.evaluation import live_comparison as controller
    from benchmarks.evaluation.experiment import digest

    path, cases = live_fixture(tmp_path, monkeypatch)
    output = tmp_path / "output"
    plan = controller.inspect_execution(path, cases, output, "formal", 2220)
    original, count = controller.verify_pack, 0

    def changed_between_checks(*args):
        nonlocal count
        result = original(*args)
        count += 1
        if count >= 2:
            result["identity"]["runtime"]["source_hash"] = "another-valid-snapshot"
            result["identity_hash"] = digest(result["identity"])
        return result

    monkeypatch.setattr(controller, "verify_pack", changed_between_checks)
    with pytest.raises(ValueError, match="authorization"):
        controller.execute_comparison(
            path, cases, output, "formal", 2220, approval(plan), credential_getter=no_credential
        )
    assert not output.exists()
