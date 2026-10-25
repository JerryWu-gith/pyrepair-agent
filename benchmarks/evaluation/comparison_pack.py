"""Offline comparison preparation. Controller identity is never a worker input."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from pyrepair.config import ALLOWED_MODELS
from pyrepair.repair_agent import SYSTEM_PROMPT

from .agent_input import (
    PublicTaskSpec,
    prepare_agent_input,
    public_task_contract,
    stage_public_snapshot,
    validate_public_input,
)
from .agent_test_runner import DockerAgentTestRunner
from .cases import case_fingerprint, contained
from .comparison_budget import checked_path, write_new
from .comparison_evidence import capture_evidence, read_evidence
from .comparison_methods import BASELINE_PROMPT
from .container_protocol import read_json
from .docker_runner import DockerTestRunner
from .experiment import digest, runtime_identity
from .grading import validate_case
from .layered_assets import load_regression
from .layered_grading import validate_layered


def file_hash(path):
    return hashlib.sha256(checked_path(path).read_bytes()).hexdigest()


def _verify_public_contract(case, repo, evidence):
    """Bind both role-visible texts to the grader, not merely to their own hashes."""
    expected = public_task_contract(case)
    if (repo / "TASK.md").read_bytes() != expected.encode("utf-8"):
        raise ValueError("public task contract differs from grader edit scope")
    context = evidence["context"]
    if context["task_contract"] != expected or not context["repo_overview"].startswith(
        "Public task contract:\n" + expected + "\n"
    ):
        raise ValueError("public evidence contract differs from grader edit scope")


def paired_slots(case_ids, trials):
    if (
        not isinstance(case_ids, list)
        or not case_ids
        or len(case_ids) != len(set(case_ids))
        or type(trials) is not int
        or not 1 <= trials <= 100
    ):
        raise ValueError("invalid comparison schedule")
    for name in case_ids:
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name) is None
        ):
            raise ValueError("invalid comparison case id")
    slots = []
    for index, case_id in enumerate(case_ids):
        for trial in range(1, trials + 1):
            methods = (
                ("single-shot", "full-agent")
                if (index + trial) % 2
                else ("full-agent", "single-shot")
            )
            for method in methods:
                slots.append(
                    {
                        "slot": f"{case_id}--{trial}--{method}",
                        "case_id": case_id,
                        "trial": trial,
                        "method": method,
                    }
                )
    return slots


def environment_identity(lock):
    lock = checked_path(lock)
    verified = DockerTestRunner(lock).assert_environment_verified()
    return {
        "lock_path": str(lock),
        "lock_sha256": file_hash(lock),
        "check_sha256": file_hash(lock.with_name("environment-check.json")),
        "verified_hash": verified["environment_hash"],
        "image_id": verified["image_id"],
    }


def comparison_config(model, trials):
    if model not in ALLOWED_MODELS:
        raise ValueError("unsupported comparison model")
    return {
        "model": model,
        "endpoint": "https://api.deepseek.com",
        "trials": trials,
        "thinking": "enabled",
        "reasoning_effort": "high",
        "provider_defaults": ["temperature", "seed", "max_tokens"],
        "max_attempts": 3,
        "max_tool_calls": 8,
        "max_model_turns_per_attempt": 11,
        "max_calls_full_agent": 36,
        "max_calls_single_shot": 1,
        "provider_retries": 0,
        "sdk_retries": 0,
        "worker_timeout": 1800,
        "baseline_prompt": BASELINE_PROMPT,
        "repair_prompt": SYSTEM_PROMPT,
        "tool_review_prompts_identity": "included in runtime source_hash",
        "output_format": "plain-unified-diff-or-single-diff/patch-fence-r1",
        "backend": "verified-docker",
        "evidence_policy": "exact-public-facts-r2",
        "assessment_policy": "layered-core-and-independent-public-extension-r1",
        "scope": "whole-workflow, not equal-compute or single-component ablation",
    }


def _runtime():
    value = runtime_identity()
    script = Path(__file__).resolve().parents[1] / "run_comparison.py"
    live_script = script.with_name("run_live_comparison.py")
    goldset_script = script.with_name("run_goldset50.py")
    return {
        **value,
        "comparison_cli_hash": file_hash(script) if script.is_file() else None,
        "live_comparison_cli_hash": file_hash(live_script) if live_script.is_file() else None,
        "goldset_cli_hash": file_hash(goldset_script) if goldset_script.is_file() else None,
    }


def _calibration_files(root):
    return {
        p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*")) if p.is_file()
    }


def _collection(validation, scope):
    nodes = (
        validation.get("extended", {}).get("expected_nodes") if validation.get("extended") else None
    )
    if scope is not None:
        if (
            not isinstance(nodes, list)
            or not nodes
            or any(
                not isinstance(n, str)
                or n.partition("::")[0] not in scope["paths"]
                or not n.partition("::")[2]
                for n in nodes
            )
            or len(nodes) != len(set(nodes))
            or not set(scope["required"]) <= set(nodes)
        ):
            raise ValueError("missing or invalid complete regression collection")
        return sorted(nodes)
    if nodes is not None:
        raise ValueError("unexpected regression collection")
    return None


def prepare_pack(cases, output, environment_lock, model, trials=3, *, calibration_reuser=None):
    slots = paired_slots([c.id for c in cases], trials)
    config = comparison_config(model, trials)
    environment = environment_identity(environment_lock)
    runtime = _runtime()
    fingerprints = {case.id: case_fingerprint(case) for case in cases}
    scopes = {case.id: load_regression(case) for case in cases}
    output = checked_path(output)
    for case in cases:
        for source in (case.buggy, case.private):
            if output.is_relative_to(source.resolve()) or source.resolve().is_relative_to(output):
                raise ValueError("comparison output overlaps task assets")
    output.mkdir(parents=True, exist_ok=False)
    try:
        backend = DockerTestRunner(environment_lock)
        backend.assert_environment_verified()
        entries = []
        for index, case in enumerate(cases):
            key = f"c{index:02d}"
            public = output / "p" / key
            print(f"prepare {case.id}: public baseline and independent calibration", flush=True)
            with tempfile.TemporaryDirectory(prefix="comparison-input-") as temporary:
                staged = Path(temporary) / "r"
                spec = prepare_agent_input(case, staged)
                stage_public_snapshot(staged, public / "r", spec.visible_tests)
            validate_public_input(public / "r", spec)
            write_new(public / "spec.json", spec.to_dict())
            runner = DockerAgentTestRunner(environment_lock, spec, output / "control" / key / "a")
            evidence = capture_evidence(public / "r", spec, runner)
            _verify_public_contract(case, public / "r", evidence)
            write_new(public / "evidence.json", evidence)
            write_new(output / "control" / key / "regression.json", {"scope": scopes[case.id]})
            if calibration_reuser is None:
                validation = validate_layered(
                    case,
                    output / "control" / key / "v",
                    test_runner=backend,
                    core_validator=validate_case,
                )
            else:
                if scopes[case.id] is not None:
                    raise ValueError(
                        "calibration reuse cannot discard an extended regression scope"
                    )
                validation = calibration_reuser(case, output / "control" / key / "v", environment)
            write_new(output / "control" / key / "calibration.json", validation)
            if validation["status"] != "valid":
                raise ValueError(f"invalid comparison preflight: {case.id}; evidence retained")
            expected_nodes = _collection(validation, scopes[case.id])
            write_new(
                output / "control" / key / "collection.json", {"expected_nodes": expected_nodes}
            )
            if (
                case_fingerprint(case) != fingerprints[case.id]
                or load_regression(case) != scopes[case.id]
            ):
                raise ValueError("comparison case changed during preparation")
            entries.append(
                {
                    "id": case.id,
                    "revision": case.revision,
                    "source_kind": case.source_kind,
                    "split": case.split,
                    "fingerprint": fingerprints[case.id],
                    "public": f"p/{key}",
                    "spec_hash": file_hash(public / "spec.json"),
                    "evidence_hash": file_hash(public / "evidence.json"),
                    "calibration_hash": file_hash(output / "control" / key / "calibration.json"),
                    "calibration_artifacts": _calibration_files(output / "control" / key / "v"),
                    "regression_hash": None if scopes[case.id] is None else digest(scopes[case.id]),
                    "collection_hash": digest(expected_nodes),
                    **(
                        {"core_collection": validation["core_collection"]}
                        if "core_collection" in validation
                        else {}
                    ),
                }
            )
        if digest(_runtime()) != digest(runtime):
            raise ValueError("comparison runtime changed during preparation")
        if environment_identity(environment_lock) != environment:
            raise ValueError("comparison environment changed during preparation")
        if any(
            case_fingerprint(case) != fingerprints[case.id]
            or load_regression(case) != scopes[case.id]
            for case in cases
        ):
            raise ValueError("comparison case changed during preparation")
        identity = {
            "version": 2,
            "authorization": "offline-only",
            "config": config,
            "runtime": runtime,
            "environment": environment,
            "cases": entries,
            "slots": slots,
        }
        write_new(output / "pack.json", {"identity": identity, "identity_hash": digest(identity)})
    except BaseException as exc:
        write_new(
            output / "preparation-error.json",
            {"error_type": type(exc).__name__, "status": "incomplete"},
        )
        raise
    return output


def verify_pack(path, cases):
    path = checked_path(path)
    value = read_json(path / "pack.json")
    if (
        set(value) != {"identity", "identity_hash"}
        or digest(value["identity"]) != value["identity_hash"]
    ):
        raise ValueError("invalid comparison pack identity")
    identity = value["identity"]
    if (
        set(identity)
        != {"version", "authorization", "config", "runtime", "environment", "cases", "slots"}
        or identity["version"] != 2
        or identity["authorization"] != "offline-only"
    ):
        raise ValueError("invalid comparison version or authorization")
    saved = identity["config"]
    if saved != comparison_config(saved["model"], saved["trials"]):
        raise ValueError("comparison configuration changed")
    if digest(identity["runtime"]) != digest(_runtime()):
        raise ValueError("comparison runtime changed; prepare a new pack")
    if environment_identity(Path(identity["environment"]["lock_path"])) != identity["environment"]:
        raise ValueError("comparison environment changed")
    if [c.id for c in cases] != [c["id"] for c in identity["cases"]]:
        raise ValueError("comparison case selection/order changed")
    if identity["slots"] != paired_slots([c.id for c in cases], saved["trials"]):
        raise ValueError("comparison schedule changed")
    for case, entry in zip(cases, identity["cases"], strict=True):
        scope = load_regression(case)
        if (
            entry["fingerprint"] != case_fingerprint(case)
            or entry["revision"] != case.revision
            or entry["source_kind"] != case.source_kind
            or entry["split"] != case.split
            or entry["regression_hash"] != (None if scope is None else digest(scope))
        ):
            raise ValueError("comparison case fingerprint changed")
        public = contained(path, entry["public"])
        key = public.name
        for name, expected in (
            ("spec.json", entry["spec_hash"]),
            ("evidence.json", entry["evidence_hash"]),
        ):
            if file_hash(public / name) != expected:
                raise ValueError("comparison public evidence changed")
        spec = PublicTaskSpec.from_dict(read_json(public / "spec.json"))
        if (spec.case_id, spec.revision, spec.source_kind) != (
            case.id,
            case.revision,
            case.source_kind,
        ):
            raise ValueError("comparison public descriptor identity mismatch")
        validate_public_input(public / "r", spec)
        evidence = read_json(public / "evidence.json")
        read_evidence(evidence, spec)
        _verify_public_contract(case, public / "r", evidence)
        calibration = path / "control" / key / "calibration.json"
        if read_json(path / "control" / key / "regression.json") != {"scope": scope}:
            raise ValueError("comparison regression scope changed")
        collection = read_json(path / "control" / key / "collection.json")
        calibration_value = read_json(calibration)
        expected_nodes = _collection(calibration_value, scope)
        if (
            collection != {"expected_nodes": expected_nodes}
            or digest(expected_nodes) != entry["collection_hash"]
        ):
            raise ValueError("comparison collection identity changed")
        if (
            file_hash(calibration) != entry["calibration_hash"]
            or read_json(calibration)["status"] != "valid"
            or _calibration_files(path / "control" / key / "v") != entry["calibration_artifacts"]
        ):
            raise ValueError("comparison calibration changed")
    return value
