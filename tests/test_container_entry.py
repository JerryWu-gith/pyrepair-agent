"""Exercise the internal entry only on self-authored, harmless test repositories."""

import json

import pytest


def staged(tmp_path, body, *, test_path="test_owned.py"):
    from benchmarks.evaluation.container_protocol import input_inventory, inventory_hash

    staging = tmp_path / "input"
    repo = staging / "repo"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    file = repo / test_path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(body, encoding="utf-8")
    inventory = input_inventory(repo, (test_path,))
    (staging / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    request = {
        "version": 1,
        "run_id": "owned-run",
        "stage_id": "owned-stage",
        "input_hash": inventory_hash(inventory),
        "environment_hash": "a" * 64,
        "paths": [test_path],
        "required": [test_path + "::test_owned"],
        "timeout": 10,
    }
    return staging, request, tmp_path / "work", tmp_path / "output"


@pytest.mark.parametrize(
    ("action", "outcome", "assertion_failure"),
    [
        ("self.assertEqual(i, i)", "passed", False),
        ("self.assertEqual(i, 0)", "failed", True),
        ("if i: raise RuntimeError('owned error')", "failed", False),
        ("if i: self.skipTest('owned skip')", "skipped", False),
        ("raise AssertionError() if i == 0 else RuntimeError()", "failed", False),
    ],
)
def test_entry_preserves_subtests_without_duplicate_main_phases(
    tmp_path, action, outcome, assertion_failure
):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import read_stage_output

    staging, request, work, output = staged(
        tmp_path,
        "import unittest\n"
        "class TestOwned(unittest.TestCase):\n"
        "    def test_owned(self):\n"
        "        for i in (0, 1):\n"
        "            with self.subTest(i=i):\n"
        f"                {action}\n",
    )
    node = "test_owned.py::TestOwned::test_owned"
    request["required"] = [node]
    assert run_stage(request, staging, work, output) == (0 if outcome == "passed" else 1)
    result = read_stage_output(output, request)
    assert result["outcomes"] == {node: outcome}
    assert result["passed"] is (outcome == "passed")
    assert result["assertion_failures"] == ([node] if assertion_failure else [])
    assert len(result["probe"]["reports"]) == 3
    assert len(result["probe"]["subtests"]) == 2
    assert result["integrity"]["unchanged"] is True


def test_entry_preserves_pytest_fixture_subtest_failures(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import read_stage_output

    staging, request, work, output = staged(
        tmp_path,
        "def test_owned(subtests):\n"
        "    for i in (0, 1):\n"
        "        with subtests.test(i=i):\n"
        "            assert i == 0\n",
    )
    assert run_stage(request, staging, work, output) == 1
    result = read_stage_output(output, request)
    assert result["outcomes"] == {"test_owned.py::test_owned": "failed"}
    assert result["assertion_failures"] == ["test_owned.py::test_owned"]
    assert len(result["probe"]["reports"]) == 3
    assert len(result["probe"]["subtests"]) == 2


def test_entry_runs_own_test_without_inheriting_sentinel_or_shadow_probe(tmp_path, monkeypatch):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import (
        input_inventory,
        inventory_hash,
        read_stage_output,
    )

    args = staged(
        tmp_path,
        "import os\n"
        "def test_owned():\n"
        "    assert 'UNTRUSTED_SENTINEL' not in os.environ\n"
        "    assert 'DEEPSEEK_API_KEY' not in os.environ\n"
        "    assert 'PYTHONPATH' not in os.environ\n"
        "    assert 'PYTEST_ADDOPTS' not in os.environ\n",
    )
    staging, request, work, output = args
    # A repository with the same package name must not replace the trusted probe.
    shadow = staging / "repo/benchmarks/evaluation"
    shadow.mkdir(parents=True)
    (shadow.parent / "__init__.py").write_text("raise RuntimeError('shadow')\n", encoding="utf-8")
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "pytest_probe.py").write_text(
        "raise RuntimeError('shadow probe')\n", encoding="utf-8"
    )
    inventory = input_inventory(staging / "repo", tuple(request["paths"]))
    (staging / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    request["input_hash"] = inventory_hash(inventory)
    monkeypatch.setenv("UNTRUSTED_SENTINEL", "harmless-test-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    assert run_stage(request, staging, work, output) == 0
    assert read_stage_output(output, request)["passed"] is True
    assert (work / "test_owned.py").read_bytes() == (staging / "repo/test_owned.py").read_bytes()
    assert not list(work.rglob("*.pyc"))


@pytest.mark.parametrize(
    "mutation",
    [
        "Path(__file__).write_text('changed')",
        "Path('new_business.py').write_text('new')",
        "Path('pyproject.toml').unlink()",
    ],
)
def test_green_test_with_runtime_changes_is_rejected(tmp_path, mutation):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import read_stage_output

    staging, request, work, output = staged(
        tmp_path,
        "from pathlib import Path\ndef test_owned():\n    " + mutation + "\n",
        test_path="venv/test_owned.py",
    )
    original = (staging / "repo/venv/test_owned.py").read_bytes()
    assert run_stage(request, staging, work, output) == 1
    result = read_stage_output(output, request)
    assert result["returncode"] == 0
    assert result["status"] == "patch_rejected"
    assert (staging / "repo/venv/test_owned.py").read_bytes() == original


def test_entry_binds_copy_to_host_inventory_before_launch(tmp_path, monkeypatch):
    from benchmarks.evaluation import container_entry as entry

    staging, request, work, output = staged(tmp_path, "def test_owned():\n    pass\n")
    (staging / "repo/test_owned.py").write_text("raise RuntimeError('not executed')\n")
    monkeypatch.setattr(entry, "execute_tests", lambda *a: pytest.fail("must not execute"))
    assert entry.run_stage(request, staging, work, output) == 2
    assert not work.exists()
    assert not (output / "result.json").exists()
    assert "inventory" in json.loads((output / "error.json").read_text())["error"]


def test_missing_required_node_cannot_be_a_green_stage(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import read_stage_output

    staging, request, work, output = staged(tmp_path, "def test_other():\n    pass\n")
    assert run_stage(request, staging, work, output) == 2
    assert read_stage_output(output, request)["status"] == "grader_error"


def test_entry_timeout_is_recorded_without_success(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage

    staging, request, work, output = staged(
        tmp_path, "import time\ndef test_owned():\n    time.sleep(10)\n"
    )
    request["timeout"] = 1
    assert run_stage(request, staging, work, output) == 2
    assert not (output / "result.json").exists()
    assert json.loads((output / "error.json").read_text())["error_type"] == "TimeoutExpired"


def test_entry_rejects_overlapping_roots_without_writing(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage

    staging, request, work, _ = staged(tmp_path, "def test_owned():\n    pass\n")
    with pytest.raises(ValueError):
        run_stage(request, staging, work, staging / "output")
    assert not (staging / "output").exists()


def test_entry_never_reuses_nonempty_output(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage

    staging, request, work, output = staged(tmp_path, "def test_owned():\n    pass\n")
    output.mkdir()
    (output / "sentinel").write_bytes(b"keep")
    with pytest.raises(ValueError):
        run_stage(request, staging, work, output)
    assert (output / "sentinel").read_bytes() == b"keep"
    assert not work.exists()


def test_copy_mismatch_is_detected_before_execution(tmp_path, monkeypatch):
    from benchmarks.evaluation import container_entry as entry

    staging, request, work, output = staged(tmp_path, "def test_owned():\n    pass\n")
    copyfile = entry.shutil.copyfile

    def changed_copy(source, target):
        copyfile(source, target)
        if target.name == "test_owned.py":
            target.write_bytes(b"altered during copying")

    monkeypatch.setattr(entry.shutil, "copyfile", changed_copy)
    monkeypatch.setattr(entry, "execute_tests", lambda *a: pytest.fail("must not execute"))
    assert entry.run_stage(request, staging, work, output) == 2
    assert "copied inventory" in json.loads((output / "error.json").read_text())["error"]


def test_oversized_output_never_becomes_success(tmp_path, monkeypatch):
    from benchmarks.evaluation import container_protocol as protocol
    from benchmarks.evaluation.container_entry import run_stage

    staging, request, work, output = staged(
        tmp_path,
        "import os\nfrom pathlib import Path\n"
        "def test_owned():\n"
        "    Path(os.environ['PYREPAIR_EVAL_PROBE']).with_name('pytest.log').write_bytes(b'x'*4096)\n",
    )
    monkeypatch.setattr(protocol, "MAX_OUTPUT_FILE", 1024)
    assert run_stage(request, staging, work, output) == 2
    assert "size limit" in json.loads((output / "error.json").read_text())["error"]
    assert not (output / "result.json").exists()


def test_conflicting_error_artifact_cannot_produce_success(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage

    staging, request, work, output = staged(
        tmp_path,
        "import os\nfrom pathlib import Path\n"
        "def test_owned():\n"
        "    Path(os.environ['PYREPAIR_EVAL_PROBE']).with_name('error.json').write_text('{}')\n",
    )
    assert run_stage(request, staging, work, output) == 2
    assert (output / "error.json").read_text() == "{}"
