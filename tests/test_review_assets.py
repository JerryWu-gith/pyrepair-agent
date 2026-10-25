"""Reject stale selected assets before a Review client can be initialized."""

import json
import shutil
from pathlib import Path

import pytest

from benchmarks.evaluation.cases import load_cases
from benchmarks.evaluation.review_fixtures import load_prepared, prepare_review
from tests.test_review_fixtures import mini_fixtures


@pytest.mark.parametrize(
    "asset",
    ["patch", "contract", "source", "hidden", "case_manifest", "fixture_manifest", "missing"],
)
def test_selected_asset_changes_reject_before_client(tmp_path, asset):
    from benchmarks.evaluation.review_evaluation import run_review

    manifest, fixtures = mini_fixtures(tmp_path)
    case = load_cases(manifest)[0]
    out = prepare_review(manifest, fixtures, tmp_path / "prepared")
    targets = {
        "patch": fixtures / "positive.patch",
        "contract": case.description,
        "source": case.buggy / "src/app.py",
        "hidden": case.private / "hidden_tests/test_hidden.py",
        "case_manifest": manifest,
        "fixture_manifest": fixtures / "manifest.json",
        "missing": fixtures / "positive.patch",
    }
    target = targets[asset]
    if asset == "missing":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b"\n")

    def forbidden(**kwargs):
        pytest.fail("stale assets must be rejected before initializing a client")

    with pytest.raises(ValueError, match="asset|identity"):
        run_review(
            out,
            tmp_path / "run",
            live=True,
            model="deepseek-flash",
            repeats=1,
            request_cap=4,
            client_factory=forbidden,
        )
    assert not (tmp_path / "run").exists()


def test_custom_collection_does_not_depend_on_unselected_default(tmp_path, monkeypatch):
    from benchmarks.evaluation import review_fixtures

    fake_root = tmp_path / "unrelated"
    default = fake_root / "benchmarks/review_cases"
    default.mkdir(parents=True)
    (default / "note.txt").write_text("before")
    shutil.copyfile(
        review_fixtures.ROOT / "benchmarks/run_review_evaluation.py",
        fake_root / "benchmarks/run_review_evaluation.py",
    )
    monkeypatch.setattr(review_fixtures, "ROOT", fake_root)
    manifest, fixtures = mini_fixtures(tmp_path)
    out = prepare_review(manifest, fixtures, tmp_path / "prepared")
    (default / "note.txt").write_text("after")
    assert len(load_prepared(out)["inputs"]) == 2


def test_preparation_refuses_assets_changed_during_grading(tmp_path, monkeypatch):
    from benchmarks.evaluation import review_fixtures

    manifest, fixtures = mini_fixtures(tmp_path)
    case = load_cases(manifest)[0]
    real = review_fixtures.grade_patch

    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        case.description.write_text("Different public contract after baseline.", encoding="utf-8")
        return result

    monkeypatch.setattr(review_fixtures, "grade_patch", changed)
    with pytest.raises(ValueError, match="asset|identity"):
        prepare_review(manifest, fixtures, tmp_path / "prepared")
    assert not (tmp_path / "prepared/prepared.json").exists()


def test_binding_external_paths_and_invalid_locators_fail_closed(tmp_path):
    from benchmarks.evaluation.review_assets import make_asset_binding, validate_asset_binding

    manifest, fixtures = mini_fixtures(tmp_path)
    binding = make_asset_binding(manifest, fixtures, ["demo"])
    assert validate_asset_binding(binding) == fixtures.resolve()
    assert binding["fixtures"]["kind"] == "external"
    for field, replacement in [
        ("version", 2),
        ("cases", {}),
        ("fixtures", {"kind": "repository", "path": "../escape"}),
        ("fixtures", {"kind": "external", "path": "relative"}),
    ]:
        bad = json.loads(json.dumps(binding))
        bad[field] = replacement
        with pytest.raises(ValueError, match="asset|path"):
            validate_asset_binding(bad)


def test_repository_locator_is_portable_and_not_absolute():
    from benchmarks.evaluation.review_assets import make_asset_binding, validate_asset_binding

    root = Path(__file__).resolve().parents[1]
    binding = make_asset_binding(
        root / "benchmarks/manifest_v2.json", root / "benchmarks/review_cases", ["case_15"]
    )
    assert binding["fixtures"] == {"kind": "repository", "path": "benchmarks/review_cases"}
    assert validate_asset_binding(binding) == root / "benchmarks/review_cases"


@pytest.mark.parametrize(
    "field, relative",
    [
        ("patch", ".pyrepair/selected.patch"),
        ("patch", "case.json"),
        ("precision_test", "venv/check.py"),
    ],
)
@pytest.mark.parametrize("change", ["modify", "remove"])
def test_explicitly_selected_ignored_assets_are_still_bound(tmp_path, field, relative, change):
    manifest, fixtures = mini_fixtures(tmp_path)
    selected = fixtures / relative
    selected.parent.mkdir(parents=True, exist_ok=True)
    content = (
        (fixtures / "positive.patch").read_text(encoding="utf-8")
        if field == "patch"
        else "from app import add\n\ndef test_precision():\n    assert add(2, 3) == 5\n"
    )
    selected.write_text(content, encoding="utf-8")
    fixture_file = fixtures / "manifest.json"
    definition = json.loads(fixture_file.read_text(encoding="utf-8"))
    definition["candidates"][0][field] = relative
    fixture_file.write_text(json.dumps(definition), encoding="utf-8")
    prepared = prepare_review(manifest, fixtures, tmp_path / "prepared")
    if change == "remove":
        selected.unlink()
    else:
        selected.write_text(content + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="asset|identity"):
        load_prepared(prepared)


@pytest.mark.parametrize("change", ["modify", "remove"])
def test_explicit_hidden_test_in_ignored_directory_is_bound(tmp_path, change):
    manifest, fixtures = mini_fixtures(tmp_path)
    case = load_cases(manifest)[0]
    target = case.private / "hidden_tests/venv/test_hidden.py"
    target.parent.mkdir()
    target.write_bytes((case.private / "hidden_tests/test_hidden.py").read_bytes())
    definition = json.loads(manifest.read_text(encoding="utf-8"))
    row = definition["cases"][0]
    old, new = "hidden_tests/test_hidden.py", "hidden_tests/venv/test_hidden.py"
    for field in ("hidden_tests", "fail_to_pass", "pass_to_pass"):
        row[field] = [value.replace(old, new) for value in row[field]]
    manifest.write_text(json.dumps(definition), encoding="utf-8")
    prepared = prepare_review(manifest, fixtures, tmp_path / "prepared")
    if change == "remove":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="asset|identity"):
        load_prepared(prepared)


@pytest.mark.parametrize("operation", ["modify", "remove"])
def test_candidate_cannot_change_executed_hidden_copy_in_ignored_directory(tmp_path, operation):
    from tests.evaluation_helpers import patch

    manifest, fixtures = mini_fixtures(tmp_path)
    case = load_cases(manifest)[0]
    target = case.private / "hidden_tests/venv/test_hidden.py"
    target.parent.mkdir()
    target.write_bytes((case.private / "hidden_tests/test_hidden.py").read_bytes())
    definition = json.loads(manifest.read_text(encoding="utf-8"))
    row = definition["cases"][0]
    old, new = "hidden_tests/test_hidden.py", "hidden_tests/venv/test_hidden.py"
    for field in ("hidden_tests", "fail_to_pass", "pass_to_pass"):
        row[field] = [value.replace(old, new) for value in row[field]]
    manifest.write_text(json.dumps(definition), encoding="utf-8")
    action = (
        'target.write_text("# changed", encoding="utf-8")'
        if operation == "modify"
        else ("target.unlink()")
    )
    candidate = (
        "from pathlib import Path\n\ndef add(a, b):\n"
        '    target = Path("hidden_tests/venv/test_hidden.py")\n'
        "    if target.exists():\n"
        f"        {action}\n"
        "    return a + b\n"
    )
    (fixtures / "positive.patch").write_text(
        patch((case.buggy / "src/app.py").read_text(encoding="utf-8"), candidate),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="label"):
        prepare_review(manifest, fixtures, tmp_path / "prepared")
    assert not (tmp_path / "prepared/prepared.json").exists()
