"""Assembly checks inspect bytes/AST only; never import generated task modules."""

import ast
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from tests.test_opensource_assets import BUGGY, CASE_ID, FIXED, tree_for

MORE_OLD = (
    "def peek(self):\n"
    "    peeked = next(self)\n"
    "    if self._index is None:\n"
    "        self._index = len(self._cache)\n"
    "    self._index -= 1\n"
    "    return peeked\n"
)
MORE_NEW = MORE_OLD.replace(
    "    if self._index is None:\n",
    "    if getattr(self._cache, 'maxlen', None) == 0:\n"
    "        self._source = chain((peeked,), self._source)\n"
    "        self._index = None\n"
    "        return peeked\n"
    "    if self._index is None:\n",
)


def prepare_handwritten_source(tmp_path, monkeypatch):
    from benchmarks.evaluation import opensource_assets as assets

    responses = {}
    for commit, tree_sha, content in [(BUGGY, "a" * 40, MORE_OLD), (FIXED, "b" * 40, MORE_NEW)]:
        files = {
            "LICENSE": b"fictional fixture license",
            "more_itertools/more.py": content.encode(),
            "tests/test_more.py": b"raise RuntimeError('fixture upstream must not execute')\n",
            "tests/test_recipes.py": b"raise RuntimeError('fixture upstream must not execute')\n",
            "README.md": b"preserve whole fixture tree",
            "pyproject.toml": b"[tool.pytest.ini_options]\n",
            ".env.example": b"test-only example excluded from runtime, not from source snapshot",
        }
        api = "https://api.github.com/repos/more-itertools/more-itertools"
        responses[f"{api}/commits/{commit}"] = json.dumps(
            {
                "sha": commit,
                "commit": {"tree": {"sha": tree_sha}},
                "parents": [{"sha": BUGGY}] if commit == FIXED else [],
            }
        ).encode()
        responses[f"{api}/git/trees/{tree_sha}?recursive=1"] = json.dumps(
            tree_for(files, tree_sha)
        ).encode()
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as stream:
            for name, data in files.items():
                stream.writestr(f"more-itertools-{commit}/{name}", data)
        responses[f"https://codeload.github.com/more-itertools/more-itertools/zip/{commit}"] = (
            payload.getvalue()
        )
    monkeypatch.setattr(assets, "fetch_bytes", lambda url, **kwargs: responses[url])
    cache = tmp_path / "cache"
    assets.prepare_source(CASE_ID, cache)
    return cache


def test_assembly_preserves_source_and_separates_private_assets(tmp_path, monkeypatch):
    from benchmarks.evaluation.cases import load_cases
    from benchmarks.evaluation.opensource_assets import assemble_case

    cache = prepare_handwritten_source(tmp_path, monkeypatch)
    destination = tmp_path / "bank"
    manifest = assemble_case(CASE_ID, cache / "buggy", cache / "fixed", destination)
    case = load_cases(manifest)[0]
    assert case.source_kind == "opensource"
    assert (case.buggy / "more_itertools/more.py").read_bytes() == MORE_OLD.encode()
    assert (case.buggy / "README.md").read_bytes() == b"preserve whole fixture tree"
    assert (case.buggy / "LICENSE").read_bytes() == b"fictional fixture license"
    assert (case.buggy / ".env.example").exists()  # Snapshot stays complete.
    assert not (case.buggy / "hidden_tests").exists()
    assert not (case.buggy / "gold.patch").exists()
    assert not (case.buggy / "source-verification.json").exists()
    assert not list(case.buggy.rglob("*.pyc"))
    evidence = json.loads((case.private / "source-verification.json").read_text())
    assert evidence["status"] == "assets_prepared"
    assert evidence["nodes_status"] == "declared_not_collected"
    assert evidence["runtime_excluded"] == [".env.example"]
    assert "artificial" in evidence["overlay"]["mutant_origin"].lower()
    assert case.gold_patch.read_text() != case.wrong_patch.read_text()
    assert BUGGY not in case.description.read_text()
    assert FIXED not in case.description.read_text()


def test_generated_patch_applies_to_disposable_handwritten_copy(tmp_path, monkeypatch):
    from benchmarks.evaluation.cases import load_cases, prepare_case
    from benchmarks.evaluation.opensource_assets import assemble_case
    from benchmarks.evaluation.patching import apply_patch_checked

    cache = prepare_handwritten_source(tmp_path, monkeypatch)
    manifest = assemble_case(CASE_ID, cache / "buggy", cache / "fixed", tmp_path / "bank")
    case = load_cases(manifest)[0]
    runtime = prepare_case(case, tmp_path / "runtime")
    assert apply_patch_checked(case, runtime, case.gold_patch.read_text()) == (
        "more_itertools/more.py",
    )
    assert (runtime / "more_itertools/more.py").read_text() == MORE_NEW
    assert not (runtime / ".env.example").exists()


def test_every_declared_overlay_node_has_a_real_function_without_imports(tmp_path, monkeypatch):
    from benchmarks.evaluation.cases import load_cases
    from benchmarks.evaluation.opensource_assets import assemble_case

    cache = prepare_handwritten_source(tmp_path, monkeypatch)
    case = load_cases(
        assemble_case(
            CASE_ID,
            cache / "buggy",
            cache / "fixed",
            tmp_path / "bank",
        )
    )[0]
    for node in (*case.fail_to_pass, *case.pass_to_pass):
        filename, function = node.split("::")
        root = case.private if filename.startswith("hidden_tests/") else case.buggy
        module = ast.parse((root / filename).read_text())
        assert function in {n.name for n in module.body if isinstance(n, ast.FunctionDef)}


@pytest.mark.parametrize("target", ["buggy", "fixed"])
def test_cached_source_tampering_is_rejected_before_assembly(tmp_path, monkeypatch, target):
    from benchmarks.evaluation.opensource_assets import assemble_case

    cache = prepare_handwritten_source(tmp_path, monkeypatch)
    (cache / target / "README.md").write_bytes(b"changed")
    output = tmp_path / "bank"
    with pytest.raises(ValueError):
        assemble_case(CASE_ID, cache / "buggy", cache / "fixed", output)
    assert not output.exists()


def test_existing_task_is_never_replaced(tmp_path, monkeypatch):
    from benchmarks.evaluation.opensource_assets import assemble_case

    cache = prepare_handwritten_source(tmp_path, monkeypatch)
    output = tmp_path / "bank"
    manifest = assemble_case(CASE_ID, cache / "buggy", cache / "fixed", output)
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        assemble_case(CASE_ID, cache / "buggy", cache / "fixed", output)
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == before


def test_source_cannot_contain_assembly_output(tmp_path, monkeypatch):
    from benchmarks.evaluation.opensource_assets import assemble_case

    cache = prepare_handwritten_source(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        assemble_case(CASE_ID, cache / "buggy", cache / "fixed", cache / "buggy")
    assert not (cache / "buggy/eval_cases").exists()


@pytest.mark.parametrize("limit_kind", ["single_file", "total"])
def test_oversized_cached_snapshot_stops_before_reading_more_files(
    tmp_path,
    monkeypatch,
    limit_kind,
):
    from benchmarks.evaluation import opensource_assets as assets
    from benchmarks.evaluation.opensource_archive import ArchiveLimits

    cache = prepare_handwritten_source(tmp_path, monkeypatch)
    limits = (
        ArchiveLimits(file_bytes=10, total_bytes=1000)
        if limit_kind == "single_file"
        else ArchiveLimits(file_bytes=1000, total_bytes=70)
    )
    monkeypatch.setattr(assets, "DEFAULT_LIMITS", limits)
    original_open = Path.open

    def bounded_open(path, *args, **kwargs):
        # Sorted snapshot order is .env.example, LICENSE, README.md.
        # The first two files already exceed the selected tiny limit.
        if path == cache / "buggy/README.md":
            pytest.fail("snapshot kept reading after exceeding its size limit")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", bounded_open)
    output = tmp_path / "bank"
    with pytest.raises(ValueError, match="snapshot.*size limit"):
        assets.assemble_case(CASE_ID, cache / "buggy", cache / "fixed", output)
    assert not output.exists()


def test_boltons_reference_changes_both_modules_but_mutant_only_one(tmp_path, monkeypatch):
    from benchmarks.evaluation import opensource_assets as assets
    from benchmarks.evaluation.cases import load_cases
    from benchmarks.evaluation.patching import patch_paths

    case_id = "os_boltons_addlist_458"
    spec = assets.source_definition(case_id)
    old = b"def addlist(self, k, v):\n    if not v:\n        return\n    self[k] = list(v)\n"
    fixed = old.replace(b"    if not v:", b"    v = list(v)\n    if not v:")
    responses = {}
    for label, tree_sha, content in [("buggy", "a" * 40, old), ("fixed", "b" * 40, fixed)]:
        commit = spec[label + "_commit"]
        files = {
            "LICENSE": b"fixture license",
            "pyproject.toml": b"[tool.pytest.ini_options]\n",
            "boltons/dictutils.py": content,
            "boltons/urlutils.py": content,
            "tests/test_dictutils.py": b"raise RuntimeError('data only')\n",
            "tests/test_urlutils.py": b"raise RuntimeError('data only')\n",
        }
        api = "https://api.github.com/repos/mahmoud/boltons"
        responses[f"{api}/commits/{commit}"] = json.dumps(
            {
                "sha": commit,
                "commit": {"tree": {"sha": tree_sha}},
                "parents": [{"sha": spec["buggy_commit"]}] if label == "fixed" else [],
            }
        ).encode()
        responses[f"{api}/git/trees/{tree_sha}?recursive=1"] = json.dumps(
            tree_for(files, tree_sha)
        ).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as stream:
            for path, data in files.items():
                stream.writestr(f"boltons-{commit}/{path}", data)
        responses[f"https://codeload.github.com/mahmoud/boltons/zip/{commit}"] = buffer.getvalue()
    monkeypatch.setattr(assets, "fetch_bytes", lambda url, **kwargs: responses[url])
    assets.prepare_source(case_id, tmp_path / "cache")
    manifest = assets.assemble_case(
        case_id,
        tmp_path / "cache/buggy",
        tmp_path / "cache/fixed",
        tmp_path / "bank",
    )
    case = load_cases(manifest)[0]
    assert patch_paths(case.gold_patch.read_text()) == (
        "boltons/dictutils.py",
        "boltons/urlutils.py",
    )
    assert patch_paths(case.wrong_patch.read_text()) == ("boltons/dictutils.py",)
    assert any("test_query_iterator_consistency" in node for node in case.fail_to_pass)
    assert not list((tmp_path / "bank").rglob("*.pyc"))
