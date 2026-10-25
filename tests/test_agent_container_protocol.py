"""Agent diagnostics may explain bad patches, but never relax independent grading."""

import copy
import hashlib

import pytest

NODE = "test_owned.py::test_owned"


def agent_evidence(*, failed=False, target=None):
    from benchmarks.evaluation.container_protocol import inventory_hash

    inventory = {"test_owned.py": hashlib.sha256(b"owned").hexdigest()}
    request = {
        "version": 2,
        "mode": "agent",
        "target": target,
        "run_id": "owned-run",
        "stage_id": "owned-stage",
        "input_hash": inventory_hash(inventory),
        "environment_hash": "a" * 64,
        "paths": ["test_owned.py"],
        "required": [] if target is None else [target],
        "timeout": 10,
    }
    probe = {
        "version": 1,
        "finished": True,
        "exit_code": int(failed),
        "collected": [NODE],
        "reports": [
            {
                "nodeid": NODE,
                "when": phase,
                "outcome": "failed" if phase == "call" and failed else "passed",
                "wasxfail": False,
                **({"exception_type": "AssertionError"} if phase == "call" and failed else {}),
            }
            for phase in ("setup", "call", "teardown")
        ],
        "collection_errors": [],
        "failures": [
            {
                "node_id": NODE,
                "phase": "call",
                "outcome": "failed",
                "exception_type": "AssertionError",
                "summary": "assert 1 == 2",
                "traceback": "/work/test_owned.py:2: AssertionError",
                "duration_ms": 1,
            }
        ]
        if failed
        else [],
    }
    result = {
        **{
            k: request[k]
            for k in ("version", "run_id", "stage_id", "input_hash", "environment_hash")
        },
        "pytest_returncode": int(failed),
        "probe": probe,
        "integrity": {"before": inventory, "after": dict(inventory), "unchanged": True},
    }
    return request, result


@pytest.mark.parametrize("failed", [False, True])
def test_agent_v2_returns_valid_execution_for_pass_or_assertion_failure(failed):
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = agent_evidence(failed=failed, target=NODE)
    checked = validate_stage_result(result, request)

    assert checked["status"] == ("failed" if failed else "passed")
    assert checked["passed"] is not failed
    assert checked["returncode"] == int(failed)
    assert checked["outcomes"] == {NODE: "failed" if failed else "passed"}
    assert len(checked["failures"]) == int(failed)


def test_agent_v2_collection_error_is_a_diagnostic_test_failure():
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = agent_evidence(failed=True)
    result["pytest_returncode"] = result["probe"]["exit_code"] = 2
    result["probe"].update(
        collected=[],
        reports=[],
        collection_errors=[{"nodeid": "test_owned.py", "outcome": "failed"}],
        failures=[
            {
                "node_id": "test_owned.py",
                "phase": "collection",
                "outcome": "failed",
                "exception_type": "SyntaxError",
                "summary": "invalid syntax",
                "traceback": "/work/app.py:1: SyntaxError",
                "duration_ms": 0,
            }
        ],
    )

    checked = validate_stage_result(result, request)

    assert checked["status"] == "failed"
    assert checked["returncode"] == 2
    assert checked["failures"][0]["exception_type"] == "SyntaxError"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_failures",
        "unknown_failure",
        "duplicate_failure",
        "missing_phase",
        "skipped",
        "xfail",
        "wrong_exit",
        "wrong_target",
        "changed_input",
        "oversized_diagnostic",
        "unknown_collection",
        "missing_exception_evidence",
        "bool_duration",
        "no_tests",
    ],
)
def test_agent_v2_rejects_incomplete_contradictory_or_untrusted_evidence(mutation):
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = agent_evidence(failed=True, target=NODE)
    probe = result["probe"]
    if mutation == "missing_failures":
        probe.pop("failures")
    elif mutation == "unknown_failure":
        probe["failures"][0]["node_id"] = "private/test_hidden.py::test_answer"
    elif mutation == "duplicate_failure":
        probe["failures"].append(copy.deepcopy(probe["failures"][0]))
    elif mutation == "missing_phase":
        probe["reports"].pop()
    elif mutation == "skipped":
        probe["reports"][1]["outcome"] = "skipped"
    elif mutation == "xfail":
        probe["reports"][1]["wasxfail"] = True
    elif mutation == "wrong_exit":
        result["pytest_returncode"] = 0
    elif mutation == "wrong_target":
        request["target"] = "test_owned.py::test_other"
        request["required"] = [request["target"]]
    elif mutation == "changed_input":
        result["integrity"]["after"] = {}
        result["integrity"]["unchanged"] = False
    elif mutation == "oversized_diagnostic":
        probe["failures"][0]["traceback"] = "x" * 16001
    elif mutation == "unknown_collection":
        probe["collection_errors"] = [{"nodeid": "outside.py", "outcome": "failed"}]
    elif mutation == "missing_exception_evidence":
        probe["failures"] = []
    elif mutation == "bool_duration":
        probe["failures"][0]["duration_ms"] = True
    elif mutation == "no_tests":
        probe.update(collected=[], reports=[], failures=[], exit_code=5)
        result["pytest_returncode"] = 5
    with pytest.raises(ValueError):
        validate_stage_result(result, request)


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "grader"},
        {"target": "../test.py::test_x"},
        {"target": "-p"},
        {"target": "test_owned.py::test_x\n--help"},
        {"private_tests": ["hidden.py"]},
        {"target": NODE, "required": []},
    ],
)
def test_agent_v2_request_rejects_unknown_modes_unsafe_selectors_and_extra_fields(changes):
    from benchmarks.evaluation.container_protocol import validate_request

    request, _ = agent_evidence()
    with pytest.raises(ValueError):
        validate_request(request | changes)
