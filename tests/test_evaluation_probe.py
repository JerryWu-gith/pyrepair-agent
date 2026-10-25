"""Observe real pytest failures in tiny, self-authored test modules."""

import json

from benchmarks.evaluation.grading import read_probe, run_tests


def test_probe_distinguishes_assertion_from_setup_import_error(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "test_owned.py").write_text(
        "import pytest\n"
        "def test_assertion():\n    assert 1 == 2\n"
        "@pytest.fixture\n"
        "def broken():\n    import pyrepair_nonexistent_fixture_dependency\n"
        "def test_setup(broken):\n    pass\n",
        encoding="utf-8",
    )
    run_tests(repo, ("test_owned.py",), tmp_path / "check.log", 15)
    probe = read_probe(tmp_path / "check.probe.json")
    failures = {(r["nodeid"], r["when"]): r for r in probe["reports"] if r["outcome"] == "failed"}
    assert failures[("test_owned.py::test_assertion", "call")]["exception_type"] == "AssertionError"
    assert (
        failures[("test_owned.py::test_setup", "setup")]["exception_type"] == "ModuleNotFoundError"
    )


def test_old_probe_without_exception_type_remains_readable(tmp_path):
    path = tmp_path / "old.json"
    data = {
        "version": 1,
        "finished": True,
        "exit_code": 1,
        "collected": ["test_owned.py::test_old"],
        "collection_errors": [],
        "reports": [
            {
                "nodeid": "test_owned.py::test_old",
                "when": "call",
                "outcome": "failed",
                "wasxfail": False,
            }
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_probe(path) == data
