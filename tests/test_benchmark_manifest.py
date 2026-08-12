import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
MANIFEST_PATH = PROJECT_ROOT / "benchmarks" / "manifest.json"


def load_cases() -> list[dict[str, str]]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["cases"]


def test_manifest_has_fifteen_balanced_non_leaking_cases() -> None:
    cases = load_cases()

    assert len(cases) == 15
    assert len({case["id"] for case in cases}) == 15
    assert Counter(case["category"] for case in cases) == {
        "condition": 3,
        "boundary": 3,
        "exception": 3,
        "state": 3,
        "conversion": 3,
    }
    forbidden = {"answer", "fixed_code", "patch"}
    assert all(not (forbidden & case.keys()) for case in cases)


def test_each_case_has_an_isolated_pytest_project() -> None:
    for case in load_cases():
        root = MANIFEST_PATH.parent / case["path"]

        assert (root / "src").is_dir(), case["id"]
        assert (root / "tests").is_dir(), case["id"]
        assert (root / "pyproject.toml").is_file(), case["id"]
        assert (root / "case.json").is_file(), case["id"]


def test_each_case_starts_with_exactly_one_failed_test() -> None:
    for case in load_cases():
        root = MANIFEST_PATH.parent / case["path"]
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        output = completed.stdout + completed.stderr

        assert completed.returncode == 1, f"{case['id']}: {output}"
        assert "1 failed" in output, f"{case['id']}: {output}"


def test_root_suite_does_not_collect_intentionally_failing_case_tests() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    assert "benchmarks/cases" not in output.replace("\\", "/")
