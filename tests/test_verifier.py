from collections import deque
from pathlib import Path

from pyrepair.models import FileChange, PatchSnapshot, PytestFailure
from pyrepair.models import TestRun as PytestRun
from pyrepair.policy import PatchPolicyGate
from pyrepair.verifier import Verifier


class FakeTestRunner:
    def __init__(self, runs: list[PytestRun]) -> None:
        self.runs = deque(runs)
        self.calls: list[tuple[Path, str | None]] = []

    def run(self, repo: Path, target: str | None = None) -> PytestRun:
        self.calls.append((repo, target))
        return self.runs.popleft()


def make_failure(node_id: str, phase: str = "call") -> PytestFailure:
    return PytestFailure(
        node_id,
        phase,
        "failed",
        "AssertionError",
        "boom",
        "E AssertionError: boom",
        1,
    )


def make_run(
    exit_code: int, stdout: str, failures: tuple[PytestFailure, ...] = ()
) -> PytestRun:
    return PytestRun(
        ("python", "-m", "pytest"),
        exit_code,
        stdout,
        "",
        10,
        failures=failures,
        capture_source="plugin",
    )


def allowed_snapshot() -> PatchSnapshot:
    return PatchSnapshot(
        (
            FileChange(
                "src/app.py",
                "return a - b\n",
                "return a + b\n",
                "candidate diff",
                1,
                1,
            ),
        )
    )


def test_verify_requires_target_full_suite_and_policy():
    target = make_run(0, "1 passed")
    full = make_run(0, "12 passed")
    runner = FakeTestRunner([target, full])

    result = Verifier(runner, PatchPolicyGate()).verify(
        Path("work"),
        "tests/test_app.py::test_add",
        {"tests/test_app.py::test_add"},
        allowed_snapshot(),
    )

    assert result.passed is True
    assert result.target_run == target
    assert result.full_run == full
    assert runner.calls == [
        (Path("work"), "tests/test_app.py::test_add"),
        (Path("work"), None),
    ]


def test_verify_reports_new_failure_as_regression():
    runner = FakeTestRunner(
        [
            make_run(0, "1 passed"),
            make_run(
                1,
                "FAILED tests/test_other.py::test_other - AssertionError: unexpected",
                (make_failure("tests/test_other.py::test_other"),),
            ),
        ]
    )

    result = Verifier(runner, PatchPolicyGate()).verify(
        Path("work"),
        "tests/test_app.py::test_add",
        {"tests/test_app.py::test_add"},
        allowed_snapshot(),
    )

    assert result.full_suite_passed is False
    assert result.regression_failures == ("tests/test_other.py::test_other",)
    assert result.passed is False


def test_verify_does_not_label_baseline_failure_as_new_regression():
    original = "tests/test_app.py::test_add"
    runner = FakeTestRunner(
        [
            make_run(0, "1 passed"),
            make_run(
                1,
                f"FAILED {original} - AssertionError: still failing",
                (make_failure(original),),
            ),
        ]
    )

    result = Verifier(runner, PatchPolicyGate()).verify(
        Path("work"), original, {original}, allowed_snapshot()
    )

    assert result.full_suite_passed is False
    assert result.regression_failures == ()
    assert result.passed is False


def test_verify_short_circuits_full_suite_when_target_still_fails():
    target = make_run(1, "FAILED tests/test_app.py::test_add - AssertionError")
    runner = FakeTestRunner([target])

    result = Verifier(runner, PatchPolicyGate()).verify(
        Path("work"),
        "tests/test_app.py::test_add",
        {"tests/test_app.py::test_add"},
        allowed_snapshot(),
    )

    assert result.target_passed is False
    assert result.full_suite_passed is False
    assert result.target_run == target
    assert result.full_run is None
    assert len(runner.calls) == 1


def test_verify_rechecks_policy_after_tests_pass():
    runner = FakeTestRunner([make_run(0, "1 passed"), make_run(0, "12 passed")])
    forbidden = PatchSnapshot(
        (
            FileChange(
                "tests/test_app.py",
                "assert False\n",
                "assert True\n",
                "candidate diff",
                1,
                1,
            ),
        )
    )

    result = Verifier(runner, PatchPolicyGate()).verify(
        Path("work"),
        "tests/test_app.py::test_add",
        {"tests/test_app.py::test_add"},
        forbidden,
    )

    assert result.target_passed is True
    assert result.full_suite_passed is True
    assert result.patch_check.allowed is False
    assert result.passed is False


def test_verifier_uses_structured_failures_for_regression(tmp_path):
    full = make_run(
        1,
        "changed summary",
        (make_failure("tests/test_other.py::test_other"),),
    )
    result = Verifier(
        FakeTestRunner([make_run(0, "1 passed"), full]), PatchPolicyGate()
    ).verify(
        tmp_path,
        "tests/test_app.py::test_add",
        {"tests/test_app.py::test_add"},
        allowed_snapshot(),
    )

    assert result.regression_failures == ("tests/test_other.py::test_other",)
