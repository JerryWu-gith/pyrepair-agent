"""Read-only index of offline calibrations, never model authorization or scores."""

from __future__ import annotations

import re
from pathlib import Path

from .cases import EvaluationCase, case_fingerprint, contained
from .catalog_source_cache import json_bytes, read_bounded, sha256
from .grading import (
    _docker_hidden_calibration_matches,
    _hidden_outcomes_calibrate,
    _stage_system_error,
)


def _stage(stage: dict, environment: str) -> None:
    if (
        _stage_system_error(stage, opensource=True)
        or stage.get("started") is not True
        or stage.get("cleanup_errors") != []
        or not isinstance(stage.get("identity"), dict)
        or stage["identity"].get("environment_hash") != environment
        or stage.get("collection_errors", stage.get("probe", {}).get("collection_errors", []))
        or stage.get("skipped", [])
    ):
        raise ValueError("calibration stage has environment, integrity or collection errors")


def _nodes(case: EvaluationCase, *, hidden: bool) -> tuple[str, ...]:
    paths = case.hidden_tests if hidden else case.visible_tests
    return tuple(
        n for n in (*case.fail_to_pass, *case.pass_to_pass) if n.partition("::")[0] in paths
    )


def _passed(stage: dict, required: tuple[str, ...]) -> bool:
    return (
        stage.get("status") == "passed"
        and stage.get("passed") is True
        and stage.get("returncode") == 0
        and stage.get("outcomes") == dict.fromkeys(required, "passed")
    )


def _full_collection(case: EvaluationCase, record: dict):
    outcomes = record.get("baseline", {}).get("outcomes")
    if not isinstance(outcomes, dict):
        raise TypeError("missing baseline collection")
    declared = set(case.fail_to_pass + case.pass_to_pass)
    extra = set(outcomes) - declared
    if (
        not declared <= set(outcomes)
        or any(
            not isinstance(n, str)
            or not n.partition("::")[2]
            or n.partition("::")[0] not in case.visible_tests + case.hidden_tests
            for n in outcomes
        )
        or (extra and case.source_kind != "synthetic")
        or any(outcomes[n] != "passed" for n in extra)
    ):
        raise ValueError("unregistered or invalid baseline collection")
    return {
        stage: sorted(n for n in outcomes if n.partition("::")[0] in paths)
        for stage, paths in (("visible", case.visible_tests), ("hidden", case.hidden_tests))
    }, sorted(extra)


def _check(case: EvaluationCase, record: dict, environment: str) -> None:
    if record.get("status") != "valid" or record.get("system_error") is not False:
        raise ValueError("conflicting or invalid calibration for the same task fingerprint")
    baseline, reference, mutant = (record.get(k, {}) for k in ("baseline", "reference", "mutant"))
    stages = [baseline, *(g.get(k, {}) for g in (reference, mutant) for k in ("visible", "hidden"))]
    for stage in stages:
        _stage(stage, environment)
    collection, extra = _full_collection(case, record)
    expected = {
        **dict.fromkeys(case.fail_to_pass, "failed"),
        **dict.fromkeys(case.pass_to_pass, "passed"),
        **dict.fromkeys(extra, "passed"),
    }
    if (
        baseline.get("status") != "failed"
        or baseline.get("returncode") != 1
        or baseline.get("outcomes") != expected
        or (
            case.source_kind == "opensource"
            and not set(case.fail_to_pass) <= set(baseline.get("assertion_failures", []))
        )
        or reference.get("status") != "passed"
        or not _passed(reference["visible"], tuple(collection["visible"]))
        or not _passed(reference["hidden"], tuple(collection["hidden"]))
        or mutant.get("status") != "hidden_failed"
        or not _passed(mutant["visible"], tuple(collection["visible"]))
        or set(mutant["hidden"].get("outcomes", {})) != set(collection["hidden"])
        or not (
            _docker_hidden_calibration_matches(
                mutant["hidden"],
                _nodes(case, hidden=True),
                tuple(n for n in case.fail_to_pass if n.partition("::")[0] in case.hidden_tests),
            )
            if case.source_kind == "opensource"
            else _hidden_outcomes_calibrate(mutant["hidden"], _nodes(case, hidden=True))
        )
    ):
        raise ValueError(
            "calibration outcomes do not establish buggy/reference/incomplete behavior"
        )


def collect_calibrations(
    cases: list[EvaluationCase],
    roots: list[Path],
    environment_hash: str,
    *,
    include_synthetic: bool = False,
) -> dict:
    """Re-use only identical task bytes, metadata and environment.

    Old-revision evidence is retained but cannot qualify current assets. An
    invalid record for the SAME fingerprint is a conflict, not a sample to hide.
    This verifies saved evidence, not a fresh Docker-engine safety attestation.
    """
    if (
        not isinstance(environment_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", environment_hash) is None
        or not cases
        or not roots
        or len({c.id for c in cases}) != len(cases)
        or type(include_synthetic) is not bool
        or any(
            c.source_kind
            not in ({"opensource", "synthetic"} if include_synthetic else {"opensource"})
            for c in cases
        )
    ):
        raise ValueError("invalid opensource calibration selection or environment hash")
    rows = []
    for case in cases:
        fingerprint = case_fingerprint(case)
        matches = []
        for root in roots:
            path = contained(root, case.id + "/validation.json")
            if not path.exists():
                continue
            raw = read_bounded(path)
            record = json_bytes(raw)
            if record.get("case_id") != case.id:
                raise ValueError("calibration case identity mismatch")
            if record.get("fingerprint") != fingerprint:
                continue
            _check(case, record, environment_hash)
            matches.append(
                {"validation_path": str(path.resolve()), "validation_sha256": sha256(raw)}
            )
        if not matches:
            raise ValueError("no matching valid calibration for " + case.id)
        chosen = json_bytes(read_bounded(Path(matches[0]["validation_path"])))
        collection, additional = _full_collection(case, chosen)
        rows.append(
            {
                "case_id": case.id,
                "revision": case.revision,
                "split": case.split,
                "repository": case.origin.get("repository"),
                "fingerprint": fingerprint,
                "environment_hash": environment_hash,
                **matches[0],
                "matching_evidence": matches,
                "f2p_nodes": len(case.fail_to_pass),
                "p2p_nodes": len(case.pass_to_pass),
                "core_collection": collection,
                "additional_passing_nodes": additional,
            }
        )
    return {
        "version": 1,
        "kind": "offline-calibration-index",
        "status": "calibrations_verified",
        "case_count": len(rows),
        "cases": rows,
        "environment_hash": environment_hash,
        "ready_for_model_evaluation": False,
        "scope": "Saved task calibration evidence only; not a frozen fifty-task model experiment",
    }
