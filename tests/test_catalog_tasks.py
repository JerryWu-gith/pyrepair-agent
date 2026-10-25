"""Task assembly uses verified owned bytes, never imports task code."""

import copy
import hashlib
import importlib
import importlib.util
import io
import json
import zipfile

import pytest

from tests.test_catalog_references import owned_catalog


def api():
    name = "benchmarks.evaluation.catalog_tasks"
    assert importlib.util.find_spec(name) is not None, "task assembler missing"
    return importlib.import_module(name)


def fixture(tmp_path):
    from benchmarks.evaluation.catalog_references import prepare_references

    catalog, replies = owned_catalog()
    # Add a second production file to catch an ACL narrowed to gold.patch paths.
    for sha in ("a" * 40, "b" * 40):
        url = "https://codeload.github.com/owner/demo/zip/" + sha
        tree_url = (
            "https://api.github.com/repos/owner/demo/git/trees/"
            + ("c" * 40 if sha.startswith("a") else "d" * 40)
            + "?recursive=1"
        )
        tree = json.loads(replies[tree_url])
        target = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(replies[url])) as old, zipfile.ZipFile(target, "w") as new:
            for item in old.infolist():
                new.writestr(item, old.read(item))
            for path, body in {
                "pyproject.toml": b"[tool.pytest.ini_options]\n",
                "src/demo/helpers.py": b"# never imported\nVALUE = 1\n",
            }.items():
                new.writestr("demo-" + sha + "/" + path, body)
                tree["tree"].append(
                    {
                        "path": path,
                        "type": "blob",
                        "mode": "100644",
                        "size": len(body),
                        "sha": hashlib.sha1(
                            b"blob " + str(len(body)).encode() + b"\0" + body
                        ).hexdigest(),
                    }
                )
        replies[url] = target.getvalue()
        replies[tree_url] = json.dumps(tree).encode()
    refs = tmp_path / "refs"
    prepare_references(catalog, refs, fetch=replies.__getitem__)
    overlay = {
        "task": "# Returned value\nReturn right for ordinary and boundary inputs.\n",
        "public": "def test_public():\n    raise AssertionError('owned unexecuted')\n",
        "hidden": "def test_hidden():\n    raise AssertionError('private unexecuted')\n",
        "f2p_public": ["test_public"],
        "f2p_hidden": ["test_hidden"],
        "p2p_public": [],
        "p2p_hidden": [],
        "public_origin": "Owned fixture",
        "hidden_origin": "Owned fixture",
        "mutant_origin": "Artificial incomplete response",
        "mutant": {
            "keep_paths": ["src/demo/__init__.py"],
            "replacements": [
                {
                    "path": "src/demo/__init__.py",
                    "old": "value = 'right'",
                    "new": "value = 'partial'",
                }
            ],
        },
    }
    return catalog, refs, {"os_demo_7": overlay}


def test_assembler_separates_hidden_assets_and_uses_whole_package_acl(tmp_path):
    from benchmarks.evaluation.cases import load_cases

    catalog, refs, overlays = fixture(tmp_path)
    destination = tmp_path / "tasks"
    result = api().assemble_catalog(catalog, refs, destination, overlays=overlays)
    cases = load_cases(destination / "manifest.json")
    assert len(cases) == 1
    case = cases[0]
    assert case.allowed_source_paths == ("src/demo/__init__.py", "src/demo/helpers.py")
    assert case.split == "holdout"
    assert case.revision == 1
    assert case.visible_tests == ("pyrepair_public_tests/test_repro.py",)
    assert case.hidden_tests == ("hidden_tests/test_contract.py",)
    assert not (case.buggy / "hidden_tests").exists()
    assert not list(case.buggy.rglob("*.patch"))
    assert "private unexecuted" in (case.private / case.hidden_tests[0]).read_text()
    assert case.gold_patch.read_bytes() == (refs / "cases/os_demo_7/gold.patch").read_bytes()
    assert "+value = 'partial'" in case.wrong_patch.read_text()
    profile = json.loads((case.buggy / "pyrepair_imports.json").read_text())
    assert profile["modules"] == {"demo": "src/demo/__init__.py"}
    assert result["calibration_status"] == "not_run"
    assert result["ready_for_model_evaluation"] is False
    assert not list(tmp_path.rglob("*.pyc"))


@pytest.mark.parametrize("mutation", ["missing_hidden", "node", "anchor", "outside", "unknown"])
def test_bad_overlay_is_rejected_before_any_task_publication(tmp_path, mutation):
    catalog, refs, overlays = fixture(tmp_path)
    item = overlays["os_demo_7"]
    if mutation == "missing_hidden":
        item["f2p_hidden"] = []
    elif mutation == "node":
        item["f2p_public"] = ["test_does_not_exist"]
    elif mutation == "anchor":
        item["mutant"]["replacements"][0]["old"] = "absent"
    elif mutation == "outside":
        item["mutant"]["keep_paths"] = ["tests/test_demo.py"]
    else:
        item["shell_command"] = "must never execute"
    destination = tmp_path / "tasks"
    with pytest.raises(ValueError):
        api().assemble_catalog(catalog, refs, destination, overlays=overlays)
    assert not (destination / "manifest.json").exists()
    assert not (destination / "tasks").exists()


def test_assembly_rejects_changed_reference_and_preserves_existing_outputs(tmp_path):
    catalog, refs, overlays = fixture(tmp_path)
    destination = tmp_path / "tasks"
    api().assemble_catalog(catalog, refs, destination, overlays=overlays)
    before = (destination / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        api().assemble_catalog(catalog, refs, destination, overlays=overlays)
    assert (destination / "manifest.json").read_bytes() == before
    (refs / "cases/os_demo_7/gold.patch").write_text("tampered")
    with pytest.raises(ValueError):
        api().assemble_catalog(catalog, refs, tmp_path / "other", overlays=copy.deepcopy(overlays))
    assert not (tmp_path / "other/manifest.json").exists()


def test_output_dotdot_alias_cannot_write_inside_verified_source_cache(tmp_path):
    catalog, refs, overlays = fixture(tmp_path)
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    destination = sibling / ".." / "refs" / "cases" / "accidental-task-output"
    before = sorted(p.relative_to(refs).as_posix() for p in refs.rglob("*"))
    with pytest.raises(ValueError, match="overlap"):
        api().assemble_catalog(catalog, refs, destination, overlays=overlays)
    assert sorted(p.relative_to(refs).as_posix() for p in refs.rglob("*")) == before
