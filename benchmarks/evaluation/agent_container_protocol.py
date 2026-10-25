"""Version 2 Agent diagnostics; deliberately separate from grader-v1 acceptance."""

from __future__ import annotations

from . import container_protocol as base

FAILURE_FIELDS = frozenset(
    {
        "node_id",
        "phase",
        "outcome",
        "exception_type",
        "summary",
        "traceback",
        "duration_ms",
    }
)


def validate_agent_request(request: dict) -> dict:
    if (
        not isinstance(request, dict)
        or set(request) != base.REQUEST_FIELDS | {"mode", "target"}
        or type(request["version"]) is not int
        or request["version"] != 2
        or request["mode"] != "agent"
    ):
        raise base.ProtocolError("invalid Agent request fields or mode")
    legacy = {k: request[k] for k in base.REQUEST_FIELDS}
    legacy["version"] = 1
    base.validate_request(legacy)
    target = request["target"]
    if target is None:
        if request["required"]:
            raise base.ProtocolError("Agent full run must not select private required nodes")
    elif (
        not isinstance(target, str)
        or not 0 < len(target) <= 4096
        or any(ord(c) < 32 for c in target)
        or "::" not in target
        or not target.partition("::")[2]
        or request["required"] != [target]
        or target.partition("::")[0] not in request["paths"]
    ):
        raise base.ProtocolError("invalid precise Agent target")
    return request


def _bounded(value, size: int, *, allow_empty: bool = True) -> bool:
    return isinstance(value, str) and len(value) <= size and (allow_empty or bool(value))


def _failures(probe: dict, expected_pairs: set[tuple[str, str]]) -> list[dict]:
    failures = probe["failures"]
    if not isinstance(failures, list) or len(failures) > 10000:
        raise base.ProtocolError("invalid Agent failure list")
    seen = set()
    for row in failures:
        if not isinstance(row, dict) or set(row) != FAILURE_FIELDS:
            raise base.ProtocolError("invalid Agent failure fields")
        if (
            not _bounded(row["node_id"], 4096, allow_empty=False)
            or not _bounded(row["phase"], 20)
            or row["phase"] not in ("setup", "call", "teardown", "collection")
            or row["outcome"] != "failed"
            or not (
                row["exception_type"] is None
                or _bounded(row["exception_type"], 200, allow_empty=False)
            )
            or not _bounded(row["summary"], 2000)
            or not _bounded(row["traceback"], 16000, allow_empty=False)
            or type(row["duration_ms"]) is not int
            or row["duration_ms"] < 0
        ):
            raise base.ProtocolError("invalid or oversized Agent diagnostic")
        pair = (row["node_id"], row["phase"])
        if pair not in expected_pairs or pair in seen:
            raise base.ProtocolError("unknown or duplicate Agent failure")
        seen.add(pair)
    if seen != expected_pairs:
        raise base.ProtocolError("missing structured failure evidence")
    return failures


def validate_agent_result(result: dict, expected: dict) -> dict:
    validate_agent_request(expected)
    if not isinstance(result, dict) or set(result) != {
        *base.IDENTITY,
        "pytest_returncode",
        "probe",
        "integrity",
    }:
        raise base.ProtocolError("invalid Agent result fields")
    if type(result["version"]) is not int or any(result[k] != expected[k] for k in base.IDENTITY):
        raise base.ProtocolError("Agent stage identity mismatch")
    code, probe, integrity = result["pytest_returncode"], result["probe"], result["integrity"]
    if type(code) is not int or code not in (0, 1, 2, 4):
        raise base.ProtocolError("Agent pytest internal/usage/no-tests execution error")
    if not isinstance(integrity, dict) or set(integrity) != {"before", "after", "unchanged"}:
        raise base.ProtocolError("invalid Agent integrity fields")
    base.validate_inventory(integrity["before"])
    base.validate_inventory(integrity["after"])
    if (
        integrity["unchanged"] is not True
        or integrity["before"] != integrity["after"]
        or base.inventory_hash(integrity["before"]) != expected["input_hash"]
    ):
        raise base.ProtocolError("Agent test input integrity changed")
    fields = {
        "version",
        "finished",
        "collected",
        "reports",
        "collection_errors",
        "exit_code",
        "failures",
    }
    if not isinstance(probe, dict) or not fields <= probe.keys() <= fields | {"subtests"}:
        raise base.ProtocolError("invalid or missing Agent probe fields")
    outcomes = base._probe_outcomes(probe, expected)
    if probe["exit_code"] != code:
        raise base.ProtocolError("Agent pytest exit code mismatch")
    pairs = set()
    for row in probe["collection_errors"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"nodeid", "outcome"}
            or not isinstance(row["nodeid"], str)
            or row["nodeid"] not in expected["paths"]
            or (
                expected["target"] is not None
                and row["nodeid"] != expected["target"].partition("::")[0]
            )
            or row["outcome"] != "failed"
        ):
            raise base.ProtocolError("unknown or skipped Agent collection failure")
        pair = (row["nodeid"], "collection")
        if pair in pairs:
            raise base.ProtocolError("duplicate Agent collection failure")
        pairs.add(pair)
    phases = {node: {} for node in probe["collected"]}
    for row in probe["reports"]:
        if row["outcome"] == "skipped" or row["wasxfail"]:
            raise base.ProtocolError("Agent tests were skipped or xfailed")
        phases[row["nodeid"]][row["when"]] = row["outcome"]
        if row["outcome"] == "failed":
            pairs.add((row["nodeid"], row["when"]))
    for rows in phases.values():
        if not rows and probe["collection_errors"]:
            # Pytest can collect healthy modules before another module aborts
            # collection. These nodes legitimately have no runtest phases.
            continue
        needed = (
            {"setup", "teardown"}
            if rows.get("setup") == "failed"
            else {"setup", "call", "teardown"}
        )
        if set(rows) != needed:
            raise base.ProtocolError("incomplete Agent pytest phases")
    subtests = probe.get("subtests", [])
    if not isinstance(subtests, list):
        raise base.ProtocolError("invalid Agent subtests")
    for row in subtests:
        if (
            not isinstance(row, dict)
            or row.get("nodeid") not in phases
            or row.get("when") != "call"
            or row.get("outcome") not in ("passed", "failed")
            or row.get("wasxfail") is not False
            or (row["outcome"] == "failed" and (row["nodeid"], "call") not in pairs)
        ):
            raise base.ProtocolError("invalid or unmerged Agent subtest")
    failures = _failures(probe, pairs)
    collection_failed = bool(probe["collection_errors"])
    if (
        (code in (2, 4)) != collection_failed
        or (code == 4 and expected["target"] is None)
        or (code == 0 and (pairs or any(v != "passed" for v in outcomes.values())))
        or (code == 1 and not pairs)
        or (not outcomes and not collection_failed)
    ):
        raise base.ProtocolError("Agent outcomes contradict pytest completion")
    if (
        expected["target"] is not None
        and not collection_failed
        and probe["collected"] != [expected["target"]]
    ):
        raise base.ProtocolError("Agent did not run exactly the selected target")
    passed = code == 0
    return {
        "passed": passed,
        "status": "passed" if passed else "failed",
        "returncode": code,
        "outcomes": outcomes,
        "required": list(expected["required"]),
        "probe": probe,
        "integrity": integrity,
        "failures": failures,
        "identity": {k: result[k] for k in base.IDENTITY},
        "assertion_failures": sorted(
            {
                row["nodeid"]
                for row in probe["reports"]
                if row["when"] == "call"
                and row["outcome"] == "failed"
                and row.get("exception_type") == "AssertionError"
            }
        ),
    }
