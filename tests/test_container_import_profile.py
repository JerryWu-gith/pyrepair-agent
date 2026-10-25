"""Only owned packages run on the host; upstream packages require Docker."""

import json

import pytest

from tests.test_container_entry import staged


def profiled_stage(tmp_path, *, package="packaging", profile=None):
    from benchmarks.evaluation.container_protocol import input_inventory, inventory_hash

    args = staged(
        tmp_path,
        f"import {package}\ndef test_owned():\n    assert {package}.owned_answer() == 42\n",
    )
    staging, request, _work, _output = args
    repo = staging / "repo"
    source = repo / "src" / package
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("def owned_answer():\n    return 42\n", encoding="utf-8")
    # Never allow source-layout exposure to replace the already trusted pytest.
    (repo / "src/pytest.py").write_text("raise RuntimeError('shadow pytest')\n")
    (repo / "pyrepair_imports.json").write_text(
        json.dumps(
            profile
            if profile is not None
            else {
                "version": 1,
                "roots": ["src"],
                "modules": {package: f"src/{package}/__init__.py"},
            }
        ),
        encoding="utf-8",
    )
    inventory = input_inventory(repo, tuple(request["paths"]))
    (staging / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    request["input_hash"] = inventory_hash(inventory)
    return args


@pytest.mark.parametrize("package", ["packaging", "more_itertools"])
def test_source_profile_loads_task_package_not_installed_dependency(tmp_path, package):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import read_stage_output

    staging, request, work, output = profiled_stage(tmp_path, package=package)
    assert run_stage(request, staging, work, output) == 0
    result = read_stage_output(output, request)
    assert result["passed"] is True
    assert result["integrity"]["unchanged"] is True
    log = (output / "pytest.log").read_text("utf-8")
    assert f'"{package}": "src/{package}/__init__.py"' in log


@pytest.mark.parametrize(
    "profile",
    [
        {
            "version": 1,
            "roots": ["../outside"],
            "modules": {"packaging": "src/packaging/__init__.py"},
        },
        {"version": 1, "roots": ["src"], "modules": {"pytest": "src/pytest.py"}},
        {"version": 1, "roots": ["src"], "modules": {"packaging": "src/missing.py"}},
        {"version": True, "roots": ["src"], "modules": {"packaging": "src/packaging/__init__.py"}},
        {
            "version": 1,
            "roots": ["src"],
            "modules": {"packaging": "src/packaging/__init__.py"},
            "command": "ignored",
        },
        {"version": 1, "roots": ["."], "modules": {"packaging": "src/packaging/__init__.py"}},
    ],
)
def test_invalid_import_profile_is_grader_error_not_task_failure(tmp_path, profile):
    from benchmarks.evaluation.container_entry import run_stage

    staging, request, work, output = profiled_stage(tmp_path, profile=profile)
    assert run_stage(request, staging, work, output) == 2
    assert not (output / "result.json").exists()


def test_actual_module_origin_must_match_declared_file(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import input_inventory, inventory_hash

    staging, request, work, output = profiled_stage(tmp_path)
    repo = staging / "repo"
    (repo / "src/packaging/other.py").write_text("answer = 42\n")
    profile = json.loads((repo / "pyrepair_imports.json").read_text())
    profile["modules"]["packaging"] = "src/packaging/other.py"
    (repo / "pyrepair_imports.json").write_text(json.dumps(profile))
    inventory = input_inventory(repo, tuple(request["paths"]))
    (staging / "inventory.json").write_text(json.dumps(inventory))
    request["input_hash"] = inventory_hash(inventory)
    assert run_stage(request, staging, work, output) == 2
    assert not (output / "result.json").exists()
