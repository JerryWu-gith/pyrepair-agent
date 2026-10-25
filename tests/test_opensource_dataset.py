"""Static checks only: do not import or execute any upstream task code."""

import ast
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from benchmarks.evaluation.cases import load_cases, prepare_case
from benchmarks.evaluation.patching import apply_patch_checked

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/manifest_opensource_v1.json"


@pytest.mark.parametrize("case", load_cases(MANIFEST), ids=lambda c: c.id)
def test_source_snapshot_and_license_match_recorded_git_bytes(case):
    evidence = json.loads((case.private / "source-verification.json").read_text(encoding="utf-8"))
    originals = evidence["source"]["versions"]["buggy"]["files"]
    actual = {p.relative_to(case.buggy).as_posix() for p in case.buggy.rglob("*") if p.is_file()}
    assert actual == set(originals) | {"tests/test_pyrepair_repro.py"}
    for relative, record in originals.items():
        assert hashlib.sha256((case.buggy / relative).read_bytes()).hexdigest() == record["sha256"]
    assert "LICENSE" in originals
    assert evidence["status"] == "assets_prepared"
    assert evidence["nodes_status"] == "declared_not_collected"
    for node in (*case.fail_to_pass, *case.pass_to_pass):
        filename, function = node.split("::")
        root = case.private if filename.startswith("hidden_tests/") else case.buggy
        module = ast.parse((root / filename).read_text(encoding="utf-8"))
        assert function in {n.name for n in module.body if isinstance(n, ast.FunctionDef)}


@pytest.mark.parametrize("case", load_cases(MANIFEST), ids=lambda c: c.id)
@pytest.mark.parametrize("kind", ["gold", "wrong"])
def test_real_source_patches_apply_without_running_source(case, kind, tmp_path):
    evidence = json.loads((case.private / "source-verification.json").read_text(encoding="utf-8"))
    repo = prepare_case(case, tmp_path / "copy")
    patch = case.gold_patch if kind == "gold" else case.wrong_patch
    paths = apply_patch_checked(case, repo, patch.read_text(encoding="utf-8"))
    if kind == "gold":
        assert set(paths) == set(case.allowed_source_paths)
        fixed = evidence["source"]["versions"]["fixed"]["files"]
        for path in paths:
            assert hashlib.sha256((repo / path).read_bytes()).hexdigest() == fixed[path]["sha256"]
    elif case.id == "os_boltons_addlist_458":
        assert paths == ("boltons/dictutils.py",)
        assert (repo / "boltons/urlutils.py").read_bytes() == (
            case.buggy / "boltons/urlutils.py"
        ).read_bytes()
    else:
        assert paths == ("more_itertools/more.py",)
        assert (repo / paths[0]).read_bytes() != (case.buggy / paths[0]).read_bytes()
    assert not (repo / "hidden_tests").exists()


def test_project_collection_excludes_asset_roots_using_own_sentinels(tmp_path):
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = settings["tool"]["pytest"]["ini_options"]["norecursedirs"]
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\nnorecursedirs = " + json.dumps(excluded) + "\n",
        encoding="utf-8",
    )
    for relative in (
        "benchmarks/eval_cases",
        "benchmarks/eval_private",
        "benchmarks/results",
        ".superpowers/sdd",
    ):
        root = tmp_path / relative / "example"
        root.mkdir(parents=True)
        (root / "test_do_not_import.py").write_text(
            "raise RuntimeError('external collection sentinel')\n",
            encoding="utf-8",
        )
    (tmp_path / "test_owned.py").write_text("def test_owned():\n    pass\n", encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY", "PYTEST_ADDOPTS"}
    }
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir=" + str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_owned.py::test_owned" in result.stdout
    assert "test_do_not_import" not in result.stdout
