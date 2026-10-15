import json

import pytest

from tests.evaluation_helpers import change_manifest, make_case


def test_preparation_excludes_answers_and_preserves_template(tmp_path):
    from benchmarks.evaluation.cases import load_cases, prepare_case

    manifest = make_case(tmp_path / "bank")
    case = load_cases(manifest)[0]
    (case.buggy / "case.json").write_text('{"answer": 5}', encoding="utf-8")
    cache = case.buggy / "__pycache__"
    cache.mkdir()
    (cache / "stale.pyc").write_bytes(b"stale")
    repo = prepare_case(case, tmp_path / "agent")
    assert (repo / "TASK.md").read_text() == "Return the sum of two integers, including zero.\n"
    assert (repo / "src/app.py").read_text() == "def add(a, b):\n    return a - b\n"
    assert not (repo / "case.json").exists()
    assert not (repo / "__pycache__").exists()
    assert not list(repo.rglob("*.patch"))
    assert not list(repo.rglob("test_hidden.py"))
    (repo / "src/app.py").write_text("changed\n")
    assert "a - b" in (case.buggy / "src/app.py").read_text()


@pytest.mark.parametrize(
    "field,value",
    [
        ("buggy_path", "../outside"),
        ("private_path", "C:/answers"),
        ("private_path", "private\\demo"),
        ("id", "../escape"),
        ("id", "CON"),
        ("suite", "unknown"),
        ("split", "test"),
        ("visible_tests", []),
        ("hidden_tests", []),
        ("timeout_seconds", True),
        ("revision", 0),
        ("allowed_source_paths", ["tests/test_app.py"]),
        ("fail_to_pass", ["../test.py::test_add"]),
        ("pass_to_pass", ["tests/missing.py::test_x"]),
    ],
)
def test_invalid_manifest_fails_before_execution(tmp_path, field, value):
    from benchmarks.evaluation.cases import CaseError, load_cases

    manifest = make_case(tmp_path)
    change_manifest(manifest, **{field: value})
    with pytest.raises(CaseError):
        load_cases(manifest)


def test_duplicate_ids_and_embedded_private_tree_are_rejected(tmp_path):
    from benchmarks.evaluation.cases import CaseError, load_cases

    manifest = make_case(tmp_path)
    data = json.loads(manifest.read_text())
    data["cases"].append(data["cases"][0])
    manifest.write_text(json.dumps(data))
    with pytest.raises(CaseError, match="duplicate"):
        load_cases(manifest)
    manifest = make_case(tmp_path)
    change_manifest(manifest, private_path="cases/demo")
    with pytest.raises(CaseError):
        load_cases(manifest)


def test_fingerprint_changes_when_contract_hidden_tests_or_source_changes(tmp_path):
    from benchmarks.evaluation.cases import case_fingerprint, load_cases

    case = load_cases(make_case(tmp_path))[0]
    previous = case_fingerprint(case)
    for path in [
        case.description,
        case.private / "hidden_tests/test_hidden.py",
        case.buggy / "src/app.py",
        case.gold_patch,
    ]:
        path.write_text(path.read_text() + "\n# revision\n", encoding="utf-8")
        current = case_fingerprint(case)
        assert current != previous
        previous = current


def test_existing_destination_is_never_overwritten(tmp_path):
    from benchmarks.evaluation.cases import load_cases, prepare_case

    case = load_cases(make_case(tmp_path / "bank"))[0]
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "user.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        prepare_case(case, destination)
    assert (destination / "user.txt").read_text() == "keep"
