"""Source-only metadata is not a calibrated task or an execution authority."""

import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def catalog_api():
    name = "benchmarks.evaluation.source_catalog"
    assert importlib.util.find_spec(name) is not None, "source catalog implementation is missing"
    return importlib.import_module(name)


def source_fixture():
    return {
        "version": 1,
        "kind": "pyrepair-opensource-source-catalog",
        "stage": "provenance_checked",
        "agent_baseline_commit": "c" * 40,
        "expected_count": 1,
        "minimum_repositories": 1,
        "entries": [
            {
                "id": "os_sample_7",
                "revision": 1,
                "source_kind": "opensource",
                "split": "holdout",
                "repository": "owner/sample",
                "pull_request": 7,
                "title": "Fix escaped values",
                "buggy_commit": "a" * 40,
                "fixed_commit": "b" * 40,
                "fixed_parents": ["a" * 40],
                "merged_at": "2026-01-01T00:00:00Z",
                "source_root": "src/sample",
                "reference_source_paths": ["src/sample/parser.py"],
                "upstream_test_paths": ["tests/test_parser.py"],
                "upstream_ai_assistance": "not established from inspected information",
                "legacy_manifest": None,
            }
        ],
        "exclusions": [],
    }


def test_source_review_does_not_authorize_model_evaluation():
    api = catalog_api()
    result = api.summarize_catalog(api.validate_catalog(source_fixture()))
    assert result["source_count"] == 1
    assert result["repository_count"] == 1
    assert result["repositories"] == {"owner/sample": 1}
    assert result["split_counts"] == {"dev": 0, "holdout": 1}
    assert result["ready_for_model_evaluation"] is False
    assert result["calibration_status"] == "not assessed by source catalog"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("version", 2),
        ("kind", "live-experiment"),
        ("stage", "calibrated"),
        ("agent_baseline_commit", "short"),
        ("expected_count", True),
        ("expected_count", 0),
        ("expected_count", 2),
        ("minimum_repositories", 0),
        ("minimum_repositories", 2),
        ("entries", {}),
        ("exclusions", {}),
        ("execute", True),
    ],
)
def test_malformed_catalog_does_not_become_a_source_list(field, value):
    api = catalog_api()
    data = source_fixture()
    data[field] = value
    with pytest.raises(api.CatalogError):
        api.validate_catalog(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "../escape"),
        ("revision", True),
        ("revision", 0),
        ("source_kind", "synthetic"),
        ("split", "unseen-to-model"),
        ("split", []),
        ("repository", "owner/sample/extra"),
        ("repository", "https://github.com/owner/sample"),
        ("pull_request", True),
        ("pull_request", 0),
        ("title", ""),
        ("buggy_commit", "A" * 40),
        ("fixed_commit", "a" * 40),
        ("fixed_parents", []),
        ("fixed_parents", ["d" * 40, "a" * 40]),
        ("fixed_parents", ["a" * 40, "short"]),
        ("merged_at", "not a date"),
        ("merged_at", "2026-01-01"),
        ("merged_at", "2026-02-31T00:00:00Z"),
        ("source_root", "../outside"),
        ("reference_source_paths", []),
        ("reference_source_paths", ["src/sample_extra/parser.py"]),
        ("reference_source_paths", ["src/sample/../parser.py"]),
        ("reference_source_paths", ["src/sample/parser.txt"]),
        ("reference_source_paths", ["src/sample/tests/test_parser.py"]),
        ("reference_source_paths", ["src/sample/parser.py", "src/sample/parser.py"]),
        ("upstream_test_paths", ["../test_parser.py"]),
        ("upstream_ai_assistance", False),
        ("legacy_manifest", "/outside/manifest.json"),
        ("legacy_manifest", "manifest.py"),
        ("command", "run-anything"),
    ],
)
def test_invalid_provenance_and_scope_are_rejected(field, value):
    api = catalog_api()
    data = source_fixture()
    data["entries"][0][field] = value
    with pytest.raises(api.CatalogError):
        api.validate_catalog(data)


@pytest.mark.parametrize("duplicate", ["id", "casefold_id", "repo_pr", "repo_commit"])
def test_one_defect_cannot_be_recounted_as_multiple_sources(duplicate):
    api = catalog_api()
    data = source_fixture()
    second = copy.deepcopy(data["entries"][0])
    second.update(id="os_other_8", pull_request=8, fixed_commit="d" * 40)
    if duplicate == "id":
        second["id"] = "os_sample_7"
    elif duplicate == "casefold_id":
        second["id"] = "OS_SAMPLE_7"
    elif duplicate == "repo_pr":
        second["repository"] = "OWNER/SAMPLE"
        second["pull_request"] = 7
    else:
        second["fixed_commit"] = "b" * 40
    data["entries"].append(second)
    data["expected_count"] = 2
    with pytest.raises(api.CatalogError, match="duplicate"):
        api.validate_catalog(data)


def test_two_parent_merge_uses_first_parent_not_pr_base():
    api = catalog_api()
    data = source_fixture()
    data["entries"][0]["fixed_parents"] = ["a" * 40, "d" * 40]
    assert api.validate_catalog(data)["entries"][0]["buggy_commit"] == "a" * 40


def test_validation_result_cannot_mutate_original_input():
    api = catalog_api()
    original = source_fixture()
    checked = api.validate_catalog(original)
    checked["entries"][0]["reference_source_paths"].append("src/sample/other.py")
    assert original["entries"][0]["reference_source_paths"] == ["src/sample/parser.py"]


def test_duplicate_json_keys_cannot_override_provenance(tmp_path):
    api = catalog_api()
    path = tmp_path / "catalog.json"
    path.write_text('{"version": 1, "version": 2}', encoding="utf-8")
    with pytest.raises(api.CatalogError, match="duplicate JSON key"):
        api.load_catalog(path)


def test_large_input_is_rejected_before_json_loading(tmp_path):
    api = catalog_api()
    path = tmp_path / "catalog.json"
    path.write_bytes(b" " * (512 * 1024 + 1))
    with pytest.raises(api.CatalogError, match="size"):
        api.load_catalog(path)


def test_file_loading_is_read_only(tmp_path):
    api = catalog_api()
    path = tmp_path / "catalog.json"
    encoded = json.dumps(source_fixture()).encode()
    path.write_bytes(encoded)
    assert api.load_catalog(path)["entries"][0]["pull_request"] == 7
    assert path.read_bytes() == encoded
    assert [p.name for p in tmp_path.iterdir()] == ["catalog.json"]


def test_checked_catalog_has_thirty_sources_without_recounting_revisions():
    api = catalog_api()
    path = ROOT / "benchmarks/opensource_catalog30.json"
    assert path.is_file(), "checked thirty-source catalog is missing"
    summary = api.summarize_catalog(api.load_catalog(path))
    assert summary["source_count"] == 30
    assert summary["repository_count"] >= 5
    assert summary["split_counts"] == {"dev": 2, "holdout": 28}
    assert summary["ready_for_model_evaluation"] is False


def test_legacy_sources_keep_original_ids_revisions_and_pinned_commits():
    api = catalog_api()
    catalog = ROOT / "benchmarks/opensource_catalog30.json"
    assert catalog.is_file(), "checked thirty-source catalog is missing"
    sources = api.load_catalog(catalog)["entries"]
    legacy = [e for e in sources if e["legacy_manifest"] is not None]
    assert {e["id"] for e in legacy} == {"os_more_seekable_1269", "os_boltons_addlist_458"}
    original = json.loads((ROOT / "benchmarks/manifest_opensource_v3.json").read_text())
    original_by_id = {e["id"]: e for e in original["cases"]}
    for entry in legacy:
        case = original_by_id[entry["id"]]
        assert entry["revision"] == case["revision"]
        assert entry["buggy_commit"] == case["origin"]["buggy_commit"]
        assert entry["fixed_commit"] == case["origin"]["fixed_commit"]
        assert entry["split"] == "dev"


def cli_api():
    name = "benchmarks.inspect_source_catalog"
    assert importlib.util.find_spec(name) is not None, "source inspection CLI is missing"
    return importlib.import_module(name)


def test_inspect_cli_reports_sources_not_model_readiness(capsys):
    assert cli_api().main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source_count"] == 30
    assert result["repository_count"] == 5
    assert result["ready_for_model_evaluation"] is False


def test_cli_does_not_write_a_supplied_catalog_directory(tmp_path, capsys):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source_fixture()), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert cli_api().main(["--catalog", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["source_count"] == 1
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("problem", ["missing", "invalid_json", "invalid_stage", "invalid_utf8"])
def test_bad_catalog_produces_controlled_cli_failure(problem, tmp_path, capsys):
    path = tmp_path / "source.json"
    if problem == "invalid_json":
        path.write_text("not JSON", encoding="utf-8")
    elif problem == "invalid_stage":
        data = source_fixture()
        data["stage"] = "calibrated"
        path.write_text(json.dumps(data), encoding="utf-8")
    elif problem == "invalid_utf8":
        path.write_bytes(b"\xff")
    assert cli_api().main(["--catalog", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Source catalog rejected:" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("flag", ["--execute", "--model", "--prepare"])
def test_source_inspection_cannot_start_preparation_or_paid_execution(flag):
    with pytest.raises(SystemExit) as exc:
        cli_api().main([flag])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "payload",
    [b'{"value":' + b"1" * 5000 + b"}", b"[" * 20000 + b"]" * 20000],
    ids=["long_integer", "deep_nesting"],
)
def test_parser_resource_limits_produce_controlled_cli_failure(payload, tmp_path, capsys):
    path = tmp_path / "source.json"
    path.write_bytes(payload)
    assert cli_api().main(["--catalog", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Source catalog rejected:" in captured.err
    assert "Traceback" not in captured.err
