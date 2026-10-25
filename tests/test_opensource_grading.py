from dataclasses import replace

import pytest

from benchmarks.evaluation.cases import load_cases
from tests.evaluation_helpers import make_case


@pytest.fixture
def case(tmp_path):
    return load_cases(make_case(tmp_path / "bank"))[0]


def _passed(required):
    return {
        "passed": True,
        "status": "passed",
        "returncode": 0,
        "required": list(required),
        "outcomes": {node: "passed" for node in required},
    }


def test_validation_uses_one_supplied_runner_for_baseline_reference_and_mutant(case, tmp_path):
    from benchmarks.evaluation.grading import validate_case

    calls = []

    def runner(repo, paths, output, timeout, required=()):
        calls.append((repo, tuple(paths), output, timeout, tuple(required)))
        if output.name == "baseline.log":
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "required": list(required),
                "outcomes": {
                    case.fail_to_pass[0]: "failed",
                    case.fail_to_pass[1]: "failed",
                    case.pass_to_pass[0]: "passed",
                },
            }
        if output.parent.name == "mutant" and tuple(paths) == case.hidden_tests:
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "required": list(required),
                "outcomes": {
                    node: "failed" if node == case.fail_to_pass[1] else "passed"
                    for node in required
                },
                "assertion_failures": [case.fail_to_pass[1]],
                "collection_errors": [],
                "skipped": [],
            }
        return _passed(required)

    result = validate_case(case, tmp_path / "validation", test_runner=runner)

    assert result["status"] == "valid"
    assert len(calls) == 5
    assert len({id(call[0]) for call in calls}) >= 2
    assert [call[1] for call in calls] == [
        case.visible_tests + case.hidden_tests,
        case.visible_tests,
        case.hidden_tests,
        case.visible_tests,
        case.hidden_tests,
    ]


@pytest.mark.parametrize(
    "bad_result",
    [
        {"passed": False, "status": "environment_error", "error": "daemon unavailable"},
        {
            "passed": False,
            "status": "failed",
            "backend": "docker",
            "integrity": {"before": {}, "after": {"file": "hash"}, "unchanged": False},
        },
        {
            "passed": False,
            "status": "failed",
            "backend": "docker",
            "integrity": {"before": {}, "after": {}, "unchanged": True},
        },
    ],
)
def test_validation_backend_error_or_integrity_failure_is_not_a_valid_task(
    case, tmp_path, bad_result
):
    from benchmarks.evaluation.grading import validate_case

    def runner(repo, paths, output, timeout, required=()):
        return bad_result

    result = validate_case(case, tmp_path / "validation", test_runner=runner)

    assert result["status"] == "invalid_task"
    assert result["baseline"] == bad_result
    assert result["system_error"] is True


def test_hidden_import_error_cannot_calibrate_wrong_patch(case, tmp_path):
    from benchmarks.evaluation.grading import validate_case

    def runner(repo, paths, output, timeout, required=()):
        if output.name == "baseline.log":
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "outcomes": {
                    case.fail_to_pass[0]: "failed",
                    case.fail_to_pass[1]: "failed",
                    case.pass_to_pass[0]: "passed",
                },
            }
        if output.parent.name == "mutant" and tuple(paths) == case.hidden_tests:
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "outcomes": {node: "error" for node in required},
                "assertion_failures": [],
                "collection_errors": [{"nodeid": "hidden import", "outcome": "failed"}],
                "skipped": [],
            }
        return _passed(required)

    result = validate_case(case, tmp_path / "validation", test_runner=runner)

    assert result["status"] == "invalid_task"
    assert result["mutant"]["hidden"]["collection_errors"]


@pytest.mark.parametrize(
    "failing_node",
    [
        "hidden_tests/test_hidden.py::test_zero",
        "hidden_tests/test_hidden.py::test_extra_acceptance",
    ],
    ids=["p2p", "extra-hidden"],
)
def test_synthetic_wrong_patch_can_be_rejected_by_any_clean_hidden_acceptance(
    case, tmp_path, failing_node
):
    from benchmarks.evaluation.grading import validate_case

    extra_node = "hidden_tests/test_hidden.py::test_extra_acceptance"
    hidden_file = case.private / "hidden_tests/test_hidden.py"
    hidden_file.write_text(
        hidden_file.read_text(encoding="utf-8")
        + "\ndef test_extra_acceptance():\n    assert add(-1, 1) == 0\n",
        encoding="utf-8",
    )

    def runner(repo, paths, output, timeout, required=()):
        outcomes = {node: "passed" for node in required}
        if output.name == "baseline.log":
            outcomes.update({node: "failed" for node in case.fail_to_pass})
            outcomes[case.pass_to_pass[0]] = "passed"
            outcomes[extra_node] = "passed"
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "outcomes": outcomes,
            }
        if output.parent.name == "mutant" and tuple(paths) == case.hidden_tests:
            outcomes[extra_node] = "passed"
            outcomes[failing_node] = "failed"
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "outcomes": outcomes,
                "collection_errors": [],
            }
        return _passed(required)

    result = validate_case(case, tmp_path / "validation", test_runner=runner)

    assert result["status"] == "valid"
    assert result["mutant"]["status"] == "hidden_failed"
    assert result["mutant"]["hidden"]["outcomes"][failing_node] == "failed"


def test_hidden_runtime_mutation_keeps_mutant_rejected_and_task_invalid(case, tmp_path):
    from benchmarks.evaluation.grading import validate_case

    def runner(repo, paths, output, timeout, required=()):
        if output.name == "baseline.log":
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "outcomes": {
                    case.fail_to_pass[0]: "failed",
                    case.fail_to_pass[1]: "failed",
                    case.pass_to_pass[0]: "passed",
                },
            }
        if output.parent.name == "mutant" and tuple(paths) == case.hidden_tests:
            (repo / "src/app.py").write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
            return {
                "passed": False,
                "status": "failed",
                "returncode": 1,
                "outcomes": {
                    case.fail_to_pass[1]: "failed",
                    case.pass_to_pass[0]: "passed",
                },
                "collection_errors": [],
            }
        return _passed(required)

    result = validate_case(case, tmp_path / "validation", test_runner=runner)

    assert result["mutant"]["status"] == "patch_rejected"
    assert result["status"] == "invalid_task"


def test_opensource_requires_verified_docker_runner_before_output(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    opensource = replace(case, source_kind="opensource")
    output = tmp_path / "grade"

    with pytest.raises(ValueError, match="verified Docker"):
        grade_patch(opensource, opensource.gold_patch.read_text(), output)

    assert not output.exists()


def test_verified_docker_runner_instance_can_grade_opensource_case_offline(
    case, tmp_path, monkeypatch
):
    from benchmarks.evaluation.docker_runner import DockerTestRunner
    from benchmarks.evaluation.grading import validate_case

    hidden_file = case.private / "hidden_tests/test_hidden.py"
    hidden_file.write_text(
        hidden_file.read_text(encoding="utf-8")
        + "\ndef test_more():\n    assert add(5, 7) == 12\n",
        encoding="utf-8",
    )
    case = replace(
        case,
        source_kind="opensource",
        fail_to_pass=case.fail_to_pass + ("hidden_tests/test_hidden.py::test_more",),
    )
    opensource = case
    runner = DockerTestRunner.__new__(DockerTestRunner)
    validation_output = tmp_path / "validation"
    verification_calls = []
    monkeypatch.setattr(
        DockerTestRunner,
        "assert_environment_verified",
        lambda self: (
            verification_calls.append(validation_output.exists())
            or {"backend": "docker", "image_id": "sha256:" + "a" * 64}
        ),
    )

    def offline_container_stage(self, repo, paths, output, timeout, required=()):
        if output.name == "baseline.log":
            outcomes = {node: "failed" for node in case.fail_to_pass}
            outcomes[case.pass_to_pass[0]] = "passed"
            assertions = list(case.fail_to_pass)
            status, code = "failed", 1
        elif output.parent.name == "mutant" and tuple(paths) == case.hidden_tests:
            outcomes = {node: "passed" for node in required}
            outcomes[case.fail_to_pass[1]] = "failed"
            assertions = [case.fail_to_pass[1]]
            status, code = "failed", 1
        else:
            outcomes = {node: "passed" for node in required}
            assertions = []
            status, code = "passed", 0
        return {
            "backend": "docker",
            "passed": code == 0,
            "status": status,
            "returncode": code,
            "required": list(required),
            "outcomes": outcomes,
            "assertion_failures": assertions,
            "collection_errors": [],
            "skipped": [],
            "integrity": {"before": {}, "after": {}, "unchanged": True},
        }

    monkeypatch.setattr(DockerTestRunner, "__call__", offline_container_stage)
    result = validate_case(opensource, validation_output, test_runner=runner)

    assert result["status"] == "valid"
    assert result["mutant"]["hidden"]["outcomes"][case.fail_to_pass[2]] == "passed"
    assert verification_calls == [False, True, True]
    assert len(list(validation_output.rglob("grade.json"))) == 2
