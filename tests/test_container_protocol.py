"""Protocol tests use only handwritten data, never upstream Python."""

import copy
import hashlib
import json

import pytest


def stage_fixture():
    from benchmarks.evaluation.container_protocol import inventory_hash

    inventory = {"test_owned.py": hashlib.sha256(b"owned").hexdigest()}
    request = {
        "version": 1,
        "run_id": "run-1",
        "stage_id": "visible-1",
        "input_hash": inventory_hash(inventory),
        "environment_hash": "a" * 64,
        "paths": ["test_owned.py"],
        "required": ["test_owned.py::test_ok"],
        "timeout": 10,
    }
    probe = {
        "version": 1,
        "finished": True,
        "exit_code": 0,
        "collected": ["test_owned.py::test_ok"],
        "collection_errors": [],
        "reports": [
            {
                "nodeid": "test_owned.py::test_ok",
                "when": phase,
                "outcome": "passed",
                "wasxfail": False,
            }
            for phase in ("setup", "call", "teardown")
        ],
    }
    result = {
        **{
            k: request[k]
            for k in ("version", "run_id", "stage_id", "input_hash", "environment_hash")
        },
        "pytest_returncode": 0,
        "probe": probe,
        "integrity": {"before": inventory, "after": dict(inventory), "unchanged": True},
    }
    return request, result


def test_inventory_does_not_ignore_explicit_or_business_files(tmp_path):
    from benchmarks.evaluation.container_protocol import input_inventory

    for name, data in {"pkg.py": b"x", "venv/test_hidden.py": b"assert False"}.items():
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    original = input_inventory(tmp_path, ("venv/test_hidden.py",))
    assert original == {
        "pkg.py": hashlib.sha256(b"x").hexdigest(),
        "venv/test_hidden.py": hashlib.sha256(b"assert False").hexdigest(),
    }
    (tmp_path / "venv/test_hidden.py").write_bytes(b"assert True")
    assert input_inventory(tmp_path, ("venv/test_hidden.py",)) != original
    (tmp_path / "new.py").write_bytes(b"new")
    assert "new.py" in input_inventory(tmp_path, ())
    (tmp_path / "venv/test_hidden.py").unlink()
    with pytest.raises(ValueError):
        input_inventory(tmp_path, ("venv/test_hidden.py",))


def test_inventory_rejects_link_before_reading_target(tmp_path, monkeypatch):
    from benchmarks.evaluation import container_protocol as protocol

    file = tmp_path / "test_owned.py"
    file.write_bytes(b"owned")
    monkeypatch.setattr(protocol, "is_link", lambda p: p == file)
    with pytest.raises(ValueError, match="link"):
        protocol.input_inventory(tmp_path, ("test_owned.py",))


@pytest.mark.parametrize(
    "path", ["../outside", "/tmp/test.py", "C:/test.py", "a\\b.py", "-p", "NUL.py", "a/../b.py"]
)
def test_request_rejects_unsafe_paths(path):
    from benchmarks.evaluation.container_protocol import validate_request

    request, _ = stage_fixture()
    request["paths"] = [path]
    request["required"] = []  # Isolate path checks from required-node membership.
    with pytest.raises(ValueError):
        validate_request(request)


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"timeout": True},
        {"timeout": 121},
        {"timeout": 0},
        {"run_id": "../run"},
        {"stage_id": ""},
        {"input_hash": "bad"},
        {"environment_hash": "bad"},
        {"paths": []},
        {"paths": ["test_owned.py"] * 2},
        {"required": ["other.py::test_ok"]},
        {"required": ["test_owned.py::test_ok"] * 2},
        {"extra": "not permitted"},
    ],
)
def test_request_rejects_invalid_identity_or_schema(change):
    from benchmarks.evaluation.container_protocol import validate_request

    request, _ = stage_fixture()
    request.update(change)
    with pytest.raises(ValueError):
        validate_request(request)


def test_valid_result_maps_to_existing_grader_shape():
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = stage_fixture()
    checked = validate_stage_result(result, request)
    assert checked["passed"] is True
    assert checked["status"] == "passed"
    assert checked["outcomes"] == {"test_owned.py::test_ok": "passed"}
    assert checked["required"] == ["test_owned.py::test_ok"]


@pytest.mark.parametrize(
    "problem",
    [
        "stale_id",
        "environment",
        "missing_integrity",
        "forged_unchanged",
        "wrong_before",
        "returncode_bool",
        "code_mismatch",
        "unfinished",
        "duplicate_node",
        "duplicate_phase",
        "unknown_node",
        "missing_phase",
        "missing_required",
        "malformed_exception",
    ],
)
def test_result_cannot_pass_with_missing_or_conflicting_evidence(problem):
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = stage_fixture()
    probe = result["probe"]
    if problem == "stale_id":
        result["stage_id"] = "old"
    elif problem == "environment":
        result["environment_hash"] = "b" * 64
    elif problem == "missing_integrity":
        del result["integrity"]
    elif problem == "forged_unchanged":
        result["integrity"]["after"]["new.py"] = "b" * 64
    elif problem == "wrong_before":
        result["integrity"]["before"] = {"other.py": "b" * 64}
    elif problem == "returncode_bool":
        result["pytest_returncode"] = False
    elif problem == "code_mismatch":
        result["pytest_returncode"] = 1
    elif problem == "unfinished":
        probe["finished"] = False
    elif problem == "duplicate_node":
        probe["collected"] *= 2
    elif problem == "duplicate_phase":
        probe["reports"].append(copy.deepcopy(probe["reports"][0]))
    elif problem == "unknown_node":
        probe["reports"][0]["nodeid"] = "other.py::test_ok"
    elif problem == "missing_phase":
        probe["reports"].pop()
    elif problem == "missing_required":
        probe["reports"] = []
        probe["collected"] = []
    else:
        probe["reports"][1]["exception_type"] = 1
    try:
        checked = validate_stage_result(result, request)
    except ValueError:
        return
    assert checked["passed"] is False
    assert checked["status"] == "grader_error"


def test_changed_file_rejects_an_otherwise_green_run():
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = stage_fixture()
    result["integrity"]["after"]["test_owned.py"] = "b" * 64
    result["integrity"]["unchanged"] = False
    checked = validate_stage_result(result, request)
    assert checked["passed"] is False
    assert checked["status"] == "patch_rejected"


def test_assertion_failure_retains_exception_evidence():
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = stage_fixture()
    result["pytest_returncode"] = result["probe"]["exit_code"] = 1
    result["probe"]["reports"][1].update(outcome="failed", exception_type="AssertionError")
    checked = validate_stage_result(result, request)
    assert checked["status"] == "failed"
    assert checked["probe"]["reports"][1]["exception_type"] == "AssertionError"


@pytest.mark.parametrize(
    "phase,exception,expected",
    [
        ("call", "AssertionError", ["test_owned.py::test_ok"]),
        ("call", "ValueError", []),
        ("setup", "AssertionError", []),
        ("call", None, []),
    ],
)
def test_only_call_assertions_count_as_reproduction_evidence(phase, exception, expected):
    from benchmarks.evaluation.container_protocol import validate_stage_result

    request, result = stage_fixture()
    result["pytest_returncode"] = result["probe"]["exit_code"] = 1
    row = next(r for r in result["probe"]["reports"] if r["when"] == phase)
    row["outcome"] = "failed"
    if exception is not None:
        row["exception_type"] = exception
    assert validate_stage_result(result, request)["assertion_failures"] == expected


def test_output_total_limit_is_checked_before_json_parse(tmp_path, monkeypatch):
    from benchmarks.evaluation import container_protocol as protocol

    monkeypatch.setattr(protocol, "MAX_OUTPUT_TOTAL", 6)
    (tmp_path / "result.json").write_bytes(b"xxxx")
    (tmp_path / "probe.json").write_bytes(b"xxxx")
    with pytest.raises(ValueError, match="size limit"):
        protocol.read_stage_output(tmp_path, stage_fixture()[0])


def test_duplicate_json_keys_cannot_replace_run_identity(tmp_path):
    from benchmarks.evaluation.container_protocol import read_json

    path = tmp_path / "result.json"
    path.write_text('{"run_id":"old","run_id":"current"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        read_json(path)


def test_output_bundle_matches_its_separate_evidence_files(tmp_path):
    from benchmarks.evaluation.container_protocol import read_stage_output

    request, result = stage_fixture()
    for name, value in {
        "result.json": result,
        "probe.json": result["probe"],
        "integrity.json": result["integrity"],
    }.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "pytest.log").write_text("owned test", encoding="utf-8")
    assert read_stage_output(tmp_path, request)["passed"]
    (tmp_path / "probe.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        read_stage_output(tmp_path, request)


@pytest.mark.parametrize("problem", ["extra", "linked", "oversized", "nested"])
def test_output_reader_rejects_bad_files_before_parsing(tmp_path, monkeypatch, problem):
    from benchmarks.evaluation import container_protocol as protocol

    if problem == "extra":
        (tmp_path / "unexpected.py").write_bytes(b"x")
    elif problem == "nested":
        (tmp_path / "result.json").mkdir()
    else:
        file = tmp_path / "result.json"
        file.write_bytes(b"not-json")
        if problem == "linked":
            monkeypatch.setattr(protocol, "is_link", lambda p: p == file)
        else:
            monkeypatch.setattr(protocol, "MAX_OUTPUT_FILE", 4)
    expected_error = {
        "extra": "unexpected or linked output",
        "linked": "unexpected or linked output",
        "oversized": "output size limit exceeded",
        "nested": "output must be a regular",
    }[problem]
    with pytest.raises(ValueError, match=expected_error):
        protocol.read_stage_output(tmp_path, stage_fixture()[0])
