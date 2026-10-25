"""Static asset checks: never import or execute upstream repositories on the host."""

import ast
from pathlib import Path

import pytest

from benchmarks.evaluation.agent_input import prepare_agent_input
from benchmarks.evaluation.cases import load_cases, public_files

ROOT = Path(__file__).resolve().parents[1]


def test_new_revision_preserves_legacy_bytes_and_selects_all_inherited_tests(tmp_path):
    from benchmarks.evaluation.layered_assets import build_more_revision, load_regression

    old = load_cases(ROOT / "benchmarks/manifest_opensource_v2.json")
    manifest = build_more_revision(tmp_path / "assets")
    more, boltons = load_cases(manifest)
    assert (more.id, more.revision, boltons.id, boltons.revision) == (
        "os_more_seekable_1269",
        2,
        "os_boltons_addlist_458",
        2,
    )
    original = {
        p.relative_to(old[0].buggy).as_posix(): p.read_bytes() for p in public_files(old[0].buggy)
    }
    revised = {
        p.relative_to(more.buggy).as_posix(): p.read_bytes() for p in public_files(more.buggy)
    }
    assert set(revised) - set(original) == {"tests/test_pyrepair_seekable_regression.py"}
    assert all(revised[name] == data for name, data in original.items())
    assert more.description.read_bytes() == old[0].description.read_bytes()
    for new, previous in zip((more, boltons), old, strict=True):
        assert new.gold_patch.read_bytes() == previous.gold_patch.read_bytes()
        assert new.wrong_patch.read_bytes() == previous.wrong_patch.read_bytes()
        for path in previous.hidden_tests:
            assert (new.private / path).read_bytes() == (previous.private / path).read_bytes()
    assert len(more.pass_to_pass) == 22
    upstream = ast.parse((more.buggy / "tests/test_more.py").read_text("utf-8"))
    classes = {n.name: n for n in upstream.body if isinstance(n, ast.ClassDef)}
    expected = set()
    for target, owners in {
        "SeekableTest": ("SeekableTest", "PeekableMixinTests"),
        "SequenceViewTests": ("SequenceViewTests",),
    }.items():
        for owner in owners:
            expected.update(
                f"tests/test_pyrepair_seekable_regression.py::{target}::{n.name}"
                for n in classes[owner].body
                if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
            )
    assert len(expected) == 19
    assert set(more.pass_to_pass) - set(old[0].pass_to_pass) == expected
    assert more.fail_to_pass == old[0].fail_to_pass
    assert more.visible_tests == (
        "tests/test_pyrepair_repro.py",
        "tests/test_pyrepair_seekable_regression.py",
    )
    descriptor = load_regression(more)
    assert tuple(descriptor["paths"]) == old[0].visible_tests
    assert descriptor["core_repeats"] == 3
    assert load_regression(boltons) is None
    assert load_regression(old[0]) is None
    public = prepare_agent_input(more, tmp_path / "worker")
    assert "hidden" not in str(public.to_dict())
    assert not (tmp_path / "worker/regression_opensource_v3.json").exists()
    assert not (tmp_path / "worker/hidden_tests").exists()


def test_revision_builder_refuses_overwrite(tmp_path):
    from benchmarks.evaluation.layered_assets import build_more_revision

    manifest = build_more_revision(tmp_path / "assets")
    original = manifest.read_bytes()
    with pytest.raises(FileExistsError):
        build_more_revision(tmp_path / "assets")
    assert manifest.read_bytes() == original


def test_regression_descriptor_rejects_an_unsafe_or_mismatched_scope(tmp_path):
    import json

    from benchmarks.evaluation.layered_assets import build_more_revision, load_regression

    case = load_cases(build_more_revision(tmp_path / "assets"))[0]
    path = case.root / "regression_opensource_v3.json"
    value = json.loads(path.read_text("utf-8"))
    value["cases"][0]["paths"] = ["../hidden_tests/test.py"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        load_regression(case)
