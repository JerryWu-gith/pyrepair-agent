"""Core acceptance and separately evidenced public regression. No model calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .cases import case_fingerprint, prepare_case
from .comparison_budget import checked_path, write_new
from .container_protocol import MAX_OUTPUT_FILE, read_json
from .execution_policy import require_case_backend
from .experiment import digest
from .grading import _docker_integrity_error, _tree_hashes, grade_patch, run_tests, validate_case
from .layered_assets import load_regression
from .patching import apply_patch_checked

TECHNICAL = {"environment_error", "grader_error", "timeout"}
EXTENDED = {
    "passed",
    "failed",
    "timeout",
    "environment_error",
    "grader_error",
    "interrupted",
    "not_applicable",
    "not_run_core_failed",
    "not_run_no_candidate",
}


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_evidence(path, value):
    """Controller evidence may use the existing16MiB reader bound, not model4MiB."""
    path = checked_path(path)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(data) > MAX_OUTPUT_FILE:
        raise ValueError("layered evidence exceeds16MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _save_phase(output, name, value):
    _write_evidence(output / name, value)
    write_new(output / (name + ".commit"), {"sha256": _hash(output / name)})


def _read_phase(output, name):
    path = output / name
    if read_json(output / (name + ".commit")) != {"sha256": _hash(path)}:
        raise ValueError("saved phase artifact changed")
    return read_json(path)


def _safe_timeout(test):
    if test.get("backend") != "docker":
        return True  # Only owned synthetic tests may use a host runner.
    if (
        test.get("cleanup_errors") != []
        or test.get("started") is not True
        or re.fullmatch(r"[0-9a-f]{64}", str(test.get("container_id"))) is None
    ):
        return False
    try:
        state = read_json(Path(test["artifacts"]) / "container-state.json")["State"]
        return (
            state.get("Running") is False
            and state.get("OOMKilled") is False
            and not state.get("Error")
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def run_extended(case, patch_text, output, *, test_runner=run_tests, expected_nodes=None):
    descriptor = load_regression(case)
    if descriptor is None:
        return {"status": "not_applicable", "stage": None}
    require_case_backend(
        case, "docker" if case.source_kind == "opensource" else "synthetic", test_runner
    )
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="layered-regression-") as temporary:
        repo = prepare_case(case, Path(temporary) / "r")
        if patch_text is not None:
            apply_patch_checked(case, repo, patch_text)
        before = _tree_hashes(repo)
        stage = test_runner(
            repo,
            tuple(descriptor["paths"]),
            output / "pytest.log",
            descriptor["timeout_seconds"],
            tuple(expected_nodes if expected_nodes is not None else descriptor["required"]),
        )
        status = stage.get("status", "grader_error")
        if status not in {"passed", "failed", "timeout", "environment_error", "grader_error"}:
            status = "grader_error"
        if _tree_hashes(repo) != before or stage.get("cleanup_errors", []) != []:
            status = "environment_error"
        elif status == "timeout":
            if (
                case.source_kind == "opensource" and stage.get("backend") != "docker"
            ) or not _safe_timeout(stage):
                status = "environment_error"
        elif status in {"passed", "failed"}:
            outcomes = stage.get("outcomes", {})
            if (
                _docker_integrity_error(stage, required=case.source_kind == "opensource")
                or not isinstance(outcomes, dict)
                or not set(descriptor["required"]) <= outcomes.keys()
                or expected_nodes is not None
                and set(outcomes) != set(expected_nodes)
                or any(v not in {"passed", "failed"} for v in outcomes.values())
                or stage.get("returncode") != (0 if status == "passed" else 1)
                or stage.get("passed") is not (status == "passed")
                or (status == "passed" and any(v != "passed" for v in outcomes.values()))
            ):
                status = "grader_error"
    result = {"status": status, "stage": stage}
    _write_evidence(output / "extended-result.json", result)
    return result


def _aggregate(core, extended, artifacts, identity):
    core_passed = core.get("status") == "passed"
    status = core.get("status", "grader_error")
    if core_passed:
        status = "core_passed"
        if extended["status"] in {"environment_error", "grader_error", "interrupted"}:
            status = (
                "environment_error" if extended["status"] == "environment_error" else "grader_error"
            )
    return {
        "version": 2,
        "status": status,
        "core": {"case_id": core.get("case_id"), "status": core["status"]},
        "extended": {"status": extended["status"]},
        "core_passed": core_passed,
        "fully_verified": None
        if extended["status"] == "not_applicable"
        else core_passed and extended["status"] == "passed",
        "artifacts": artifacts,
        "identity": identity,
    }


def validate_layered_grade(value, output=None, *, candidate_patch=None, frozen_case=None):
    fields = {
        "version",
        "status",
        "core",
        "extended",
        "core_passed",
        "fully_verified",
        "artifacts",
        "identity",
    }
    if not isinstance(value, dict) or set(value) != fields or value["version"] != 2:
        raise ValueError("invalid layered grade")
    if value["status"] == "simulated":
        if value != simulated_grade():
            raise ValueError("invalid simulated grade")
        return value
    if (
        not isinstance(value["core"], dict)
        or not isinstance(value["extended"], dict)
        or value["core"].get("status")
        not in {
            "passed",
            "no_patch",
            "patch_rejected",
            "visible_failed",
            "hidden_failed",
            *TECHNICAL,
        }
        or value["extended"].get("status") not in EXTENDED
        or type(value["core_passed"]) is not bool
        or value["fully_verified"] is not None
        and type(value["fully_verified"]) is not bool
        or value
        != _aggregate(value["core"], value["extended"], value["artifacts"], value["identity"])
    ):
        raise ValueError("contradictory layered grade")
    identity = value["identity"]
    if (
        not isinstance(identity, dict)
        or set(identity) != {"case", "patch", "regression", "collection"}
        or any(re.fullmatch(r"[0-9a-f]{64}", str(v)) is None for v in identity.values())
    ):
        raise ValueError("invalid layered identity")
    if (
        candidate_patch is not None
        and identity["patch"] != hashlib.sha256(candidate_patch.encode()).hexdigest()
    ):
        raise ValueError("candidate patch identity mismatch")
    if frozen_case is not None:
        for source, target in (
            ("fingerprint", "case"),
            ("regression_hash", "regression"),
            ("collection_hash", "collection"),
        ):
            if source in frozen_case and identity[target] != (
                frozen_case[source] if frozen_case[source] is not None else digest(None)
            ):
                raise ValueError("frozen case/regression identity mismatch")
    if set(value["artifacts"]) != {"core-grade.json", "extended-regression.json"}:
        raise ValueError("missing layered artifact identity")
    core_collection = frozen_case.get("core_collection") if frozen_case is not None else None
    if core_collection is not None and output is None:
        raise ValueError("frozen core collection requires saved grading evidence")
    if output is not None:
        if read_json(output / "identity.json") != identity:
            raise ValueError("saved grading identity mismatch")
        for name, expected in value["artifacts"].items():
            if _hash(output / name) != expected:
                raise ValueError("layered artifact changed")
            saved = _read_phase(output, name)
            if name == "core-grade.json" and core_collection is not None:
                if not isinstance(core_collection, dict) or set(core_collection) != {
                    "visible",
                    "hidden",
                }:
                    raise ValueError("invalid frozen core collection")
                for phase in ("visible", "hidden"):
                    expected = core_collection[phase]
                    if (
                        not isinstance(expected, list)
                        or not expected
                        or len(set(expected)) != len(expected)
                        or any(not isinstance(n, str) or "::" not in n for n in expected)
                    ):
                        raise ValueError("invalid frozen core collection nodes")
                    stage = saved.get(phase)
                    if (
                        stage is not None
                        and stage.get("status") in {"passed", "failed"}
                        and (
                            not isinstance(stage.get("outcomes"), dict)
                            or set(stage["outcomes"]) != set(expected)
                        )
                    ):
                        raise ValueError("saved grading differs from frozen core collection")
            summary = (
                {"case_id": saved.get("case_id"), "status": saved["status"]}
                if name == "core-grade.json"
                else {"status": saved["status"]}
            )
            if summary != value["core" if name == "core-grade.json" else "extended"]:
                raise ValueError("layered artifact contradicts grade")
    return value


def simulated_grade():
    return {
        "version": 2,
        "status": "simulated",
        "core": {"status": "simulated"},
        "extended": {"status": "simulated"},
        "core_passed": None,
        "fully_verified": None,
        "artifacts": {},
        "identity": None,
    }


def grade_layered(case, patch_text, output, *, test_runner=run_tests, expected_nodes=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    descriptor = load_regression(case)
    if descriptor is not None:
        if expected_nodes is None:
            if case.source_kind == "opensource":
                raise ValueError("opensource extension requires a frozen full collection")
            expected_nodes = descriptor["required"]
        expected_nodes = sorted(expected_nodes)
        if (
            len(expected_nodes) != len(set(expected_nodes))
            or not set(descriptor["required"]) <= set(expected_nodes)
            or any(
                not isinstance(n, str)
                or n.partition("::")[0] not in descriptor["paths"]
                or not n.partition("::")[2]
                or any(ord(c) < 32 for c in n)
                for n in expected_nodes
            )
        ):
            raise ValueError("invalid frozen extension collection")
    identity = {
        "case": case_fingerprint(case),
        "patch": hashlib.sha256(patch_text.encode()).hexdigest(),
        "regression": digest(descriptor),
        "collection": digest(expected_nodes),
    }
    if (output / "identity.json").exists():
        if read_json(output / "identity.json") != identity:
            raise ValueError("layered grading identity changed")
    else:
        write_new(output / "identity.json", identity)
    if (output / "result.json").exists():
        return validate_layered_grade(
            read_json(output / "result.json"), output, candidate_patch=patch_text
        )
    if (output / "core-grade.json").exists():
        core = _read_phase(output, "core-grade.json")
    elif (output / "core-started.json").exists():
        core = {
            "case_id": case.id,
            "status": "grader_error",
            "error": "interrupted core stage; no automatic replay",
        }
        _save_phase(output, "core-grade.json", core)
    else:
        write_new(output / "core-started.json", identity)
        core = grade_patch(case, patch_text, output / "core", test_runner=test_runner)
        if descriptor and not _core_nodes_match(case, core):
            core = {
                **core,
                "status": "grader_error",
                "error": "core collection differs from fixed node identities",
            }
        _save_phase(output, "core-grade.json", core)
    if (output / "extended-regression.json").exists():
        extended = _read_phase(output, "extended-regression.json")
    else:
        if core["status"] != "passed":
            extended = {
                "status": "not_run_core_failed" if patch_text.strip() else "not_run_no_candidate",
                "stage": None,
            }
        elif load_regression(case) is None:
            extended = {"status": "not_applicable", "stage": None}
        elif (output / "extended-started.json").exists():
            extended = {"status": "interrupted", "stage": None}
        else:
            write_new(output / "extended-started.json", identity)
            try:
                extended = run_extended(
                    case,
                    patch_text,
                    output / "extended",
                    test_runner=test_runner,
                    expected_nodes=expected_nodes,
                )
            except Exception as exc:  # noqa: BLE001 - preserve known core, never swallow interrupts
                extended = {
                    "status": "environment_error" if isinstance(exc, OSError) else "grader_error",
                    "stage": None,
                    "error_type": type(exc).__name__,
                }
        _save_phase(output, "extended-regression.json", extended)
    result = _aggregate(
        core,
        extended,
        {name: _hash(output / name) for name in ("core-grade.json", "extended-regression.json")},
        identity,
    )
    validate_layered_grade(result, output)
    write_new(output / "result.json", result)
    return result


def _core_nodes_match(case, grade):
    for stage, paths in (("visible", case.visible_tests), ("hidden", case.hidden_tests)):
        value = grade.get(stage)
        if isinstance(value, dict) and value.get("status") in {"passed", "failed"}:
            expected = {
                n for n in (*case.fail_to_pass, *case.pass_to_pass) if n.partition("::")[0] in paths
            }
            if set(value.get("outcomes", {})) != expected:
                return False
    return True


def validate_layered(case, output, *, test_runner=run_tests, core_validator=validate_case):
    output.mkdir(parents=True, exist_ok=False)
    descriptor = load_regression(case)
    repeats = descriptor["core_repeats"] if descriptor else 1
    cores = []
    for index in range(repeats):
        core = core_validator(case, output / f"c{index}", test_runner=test_runner)
        if descriptor and core["status"] == "valid":
            expected = set(case.fail_to_pass + case.pass_to_pass)
            if set(core["baseline"]["outcomes"]) != expected or not all(
                _core_nodes_match(case, core[k]) for k in ("reference", "mutant")
            ):
                core = {
                    **core,
                    "status": "invalid_task",
                    "error": "core collection differs from fixed node identities",
                }
        cores.append(
            {key: core[key] for key in ("case_id", "status", "fingerprint") if key in core}
        )
        if core["status"] != "valid":
            result = {"status": "invalid_task", "core": cores, "extended": None}
            write_new(output / "calibration.json", result)
            return result
    extended = None
    valid = True
    if descriptor:
        baseline = run_extended(case, None, output / "b", test_runner=test_runner)
        expected_nodes = (
            sorted(baseline.get("stage", {}).get("outcomes", {}))
            if baseline["status"] == "failed"
            else []
        )
        reference = run_extended(
            case,
            case.gold_patch.read_text("utf-8"),
            output / "r",
            test_runner=test_runner,
            expected_nodes=expected_nodes or None,
        )
        extended = {
            "baseline": {"status": baseline["status"]},
            "reference": {"status": reference["status"]},
            "expected_nodes": expected_nodes,
        }
        valid = (
            bool(expected_nodes)
            and baseline["status"] == "failed"
            and reference["status"]
            in {
                "passed",
                "timeout",
            }
        )
        if baseline["status"] == "failed":
            expected = [n for n in case.fail_to_pass if n.partition("::")[0] in descriptor["paths"]]
            valid = valid and all(
                baseline["stage"]["outcomes"].get(n) == "failed" for n in expected
            )
    result = {
        "status": "valid" if valid else "invalid_task",
        "core": cores,
        "extended": extended,
        "regression_identity": digest(descriptor),
        "evidence": {
            str(p.relative_to(output).as_posix()): _hash(p)
            for p in sorted(
                [*output.rglob("validation.json"), *output.rglob("extended-result.json")]
            )
        },
    }
    write_new(output / "calibration.json", result)
    return result
