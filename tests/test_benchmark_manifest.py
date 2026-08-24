import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pyrepair.pytest_parser import PytestParser
from pyrepair.pytest_plugin import _serialize_report
from pyrepair.testing import TestRunner as PytestRunner

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
    basetemp_root = PROJECT_ROOT / "tmp" / f"pytest-manifest-{uuid4().hex}"
    try:
        for case in load_cases():
            root = MANIFEST_PATH.parent / case["path"]
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    str(basetemp_root / case["id"]),
                ],
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
    finally:
        shutil.rmtree(basetemp_root, ignore_errors=True)


@pytest.mark.parametrize("case_id", ["case_05", "case_08"])
def test_known_pytest9_cases_produce_parseable_failure(case_id):
    root = PROJECT_ROOT / "benchmarks" / "cases" / case_id

    run = PytestRunner(10).run(root)
    report = PytestParser().parse(run)

    assert run.capture_source in {"plugin", "text"}
    assert report.parseable is True
    assert report.node_id is not None


def test_capture_plugin_serializes_benchmark_style_failure() -> None:
    report = SimpleNamespace(
        nodeid="tests/test_app.py::test_add",
        longreprtext="E AssertionError: expected 5",
        duration=0.007,
        outcome="failed",
    )

    failure = _serialize_report(report, "call")

    assert failure == {
        "node_id": "tests/test_app.py::test_add",
        "phase": "call",
        "outcome": "failed",
        "exception_type": "AssertionError",
        "summary": "E AssertionError: expected 5",
        "traceback": "E AssertionError: expected 5",
        "duration_ms": 7,
    }


def test_root_suite_does_not_collect_intentionally_failing_case_tests() -> None:
    created_child_dirs: list[Path] = []
    scratch_roots = [PROJECT_ROOT / "tmp", PROJECT_ROOT / ".pyrepair"]
    sentinel_tests = [
        ("test_tmp_sentinel.py", "test_tmp_sentinel"),
        ("test_pyrepair_sentinel.py", "test_pyrepair_sentinel"),
    ]

    try:
        nested_basetemp = PROJECT_ROOT / "tmp" / f"pytest-p0-basetemp-{uuid4().hex}"
        (PROJECT_ROOT / "tmp").mkdir(exist_ok=True)
        nested_basetemp.mkdir()
        created_child_dirs.append(nested_basetemp)

        sentinel_nodes = []
        for scratch_root, (filename, test_name) in zip(scratch_roots, sentinel_tests):
            scratch_root.mkdir(exist_ok=True)
            child_dir = scratch_root / f"pytest-p0-{uuid4().hex}"
            child_dir.mkdir()
            created_child_dirs.append(child_dir)
            (child_dir / filename).write_text(
                f"def {test_name}():\n    pass\n",
                encoding="utf-8",
            )
            relative_path = (child_dir / filename).relative_to(PROJECT_ROOT)
            sentinel_nodes.append(f"{relative_path.as_posix()}::{test_name}")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(nested_basetemp),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        output = completed.stdout + completed.stderr
        normalized_output = output.replace("\\", "/")

        assert completed.returncode == 0, output
        assert "benchmarks/cases" not in normalized_output
        assert all(node not in normalized_output for node in sentinel_nodes)
    finally:
        for child_dir in created_child_dirs:
            shutil.rmtree(child_dir)
