"""Reference preparation never claims behavioral calibration or runs source."""

import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_catalog_source_cache import owned_responses


def api():
    name = "benchmarks.evaluation.catalog_references"
    assert importlib.util.find_spec(name) is not None, "reference preparation is missing"
    return importlib.import_module(name)


def owned_catalog():
    entry, replies = owned_responses()
    return {
        "version": 1,
        "kind": "pyrepair-opensource-source-catalog",
        "stage": "provenance_checked",
        "agent_baseline_commit": "c" * 40,
        "expected_count": 1,
        "minimum_repositories": 1,
        "entries": [entry],
        "exclusions": [],
    }, replies


def test_reference_preparation_still_requires_calibration(tmp_path):
    catalog, replies = owned_catalog()
    result = api().prepare_references(catalog, tmp_path / "batch", fetch=replies.__getitem__)
    assert result["reference_count"] == 1
    assert result["unique_version_count"] == 2
    assert result["ready_for_model_evaluation"] is False
    assert result["calibration_status"] == "not_run"
    assert not list(tmp_path.rglob("*.pyc"))


def test_reference_patch_excludes_changed_upstream_tests(tmp_path):
    from benchmarks.evaluation.patching import patch_paths

    catalog, replies = owned_catalog()
    output = tmp_path / "batch"
    api().prepare_references(catalog, output, fetch=replies.__getitem__)
    patch = (output / "cases/os_demo_7/gold.patch").read_text(encoding="utf-8")
    assert patch_paths(patch) == ("src/demo/__init__.py",)
    assert "+value = 'right'" in patch
    assert "-value = 'wrong'" in patch


def test_finished_batch_resumes_without_network(tmp_path):
    catalog, replies = owned_catalog()
    output = tmp_path / "batch"
    first = api().prepare_references(catalog, output, fetch=replies.__getitem__)

    def no_network(url):
        raise AssertionError("resume must reuse completed versions: " + url)

    second = api().prepare_references(catalog, output, resume=True, fetch=no_network)
    assert first == second
    assert api().verify_references(catalog, output) == first


def test_partial_network_failure_is_preserved_and_completed_sources_are_not_refetched(tmp_path):
    catalog, replies = owned_catalog()
    output = tmp_path / "batch"
    failed_url = "https://codeload.github.com/owner/demo/zip/" + "b" * 40

    def broken_fetch(url):
        if url == failed_url:
            raise OSError("owned network failure")
        return replies[url]

    with pytest.raises(OSError, match="owned network failure"):
        api().prepare_references(catalog, output, fetch=broken_fetch)
    reports = list((output / "runs").glob("*/report.json"))
    assert len(reports) == 1
    before = reports[0].read_bytes()
    assert json.loads(before)["status"] == "source_error"
    requests = []

    def restored_fetch(url):
        requests.append(url)
        return replies[url]

    result = api().prepare_references(catalog, output, fetch=restored_fetch, resume=True)
    assert result["reference_count"] == 1
    assert len(requests) == 3
    assert failed_url in requests
    assert reports[0].read_bytes() == before
    assert len(list((output / "runs").glob("*/report.json"))) == 2


def test_changed_catalog_is_rejected_before_resume(tmp_path):
    catalog, replies = owned_catalog()
    output = tmp_path / "batch"
    api().prepare_references(catalog, output, fetch=replies.__getitem__)
    changed = copy.deepcopy(catalog)
    changed["entries"][0]["title"] = "changed task identity"
    with pytest.raises(ValueError, match="catalog"):
        api().prepare_references(changed, output, resume=True, fetch=replies.__getitem__)


def test_cached_patch_tampering_is_rejected_not_overwritten(tmp_path):
    catalog, replies = owned_catalog()
    output = tmp_path / "batch"
    api().prepare_references(catalog, output, fetch=replies.__getitem__)
    patch = output / "cases/os_demo_7/gold.patch"
    patch.write_bytes(patch.read_bytes() + b"tampered")
    before = patch.read_bytes()
    with pytest.raises(ValueError):
        api().verify_references(catalog, output)
    with pytest.raises(ValueError):
        api().prepare_references(catalog, output, resume=True, fetch=replies.__getitem__)
    assert patch.read_bytes() == before


def test_existing_writer_lock_is_never_removed_automatically(tmp_path):
    catalog, replies = owned_catalog()
    output = tmp_path / "batch"
    api().prepare_references(catalog, output, fetch=replies.__getitem__)
    lock = output / "writer.lock"
    lock.write_bytes(b"some other owner")
    with pytest.raises(FileExistsError):
        api().prepare_references(catalog, output, resume=True, fetch=replies.__getitem__)
    assert lock.read_bytes() == b"some other owner"


def test_missing_production_change_cannot_be_silently_ignored(tmp_path):
    catalog, replies = owned_catalog()
    catalog["entries"][0]["reference_source_paths"] = ["src/demo/unmodified.py"]
    with pytest.raises(ValueError, match="production"):
        api().prepare_references(catalog, tmp_path / "batch", fetch=replies.__getitem__)


def cli_api():
    name = "benchmarks.prepare_catalog_references"
    assert importlib.util.find_spec(name) is not None, "reference CLI is missing"
    return importlib.import_module(name)


def test_cli_verify_only_is_offline_and_does_not_create_reports(tmp_path, capsys):
    catalog, replies = owned_catalog()
    output = tmp_path / "batch"
    api().prepare_references(catalog, output, fetch=replies.__getitem__)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    reports = {
        p.relative_to(output).as_posix(): p.read_bytes()
        for p in (output / "runs").rglob("*")
        if p.is_file()
    }
    assert cli_api().main(["--catalog", str(path), "--output", str(output), "--verify-only"]) == 0
    assert json.loads(capsys.readouterr().out)["ready_for_model_evaluation"] is False
    assert {
        p.relative_to(output).as_posix(): p.read_bytes()
        for p in (output / "runs").rglob("*")
        if p.is_file()
    } == reports


def test_cli_has_no_model_execution_option(tmp_path):
    with pytest.raises(SystemExit) as error:
        cli_api().main(["--output", str(tmp_path / "batch"), "--model", "anything"])
    assert error.value.code == 2


def test_preparation_can_publish_without_directory_rename(tmp_path, monkeypatch):
    catalog, replies = owned_catalog()

    def unavailable_rename(*args, **kwargs):
        raise PermissionError("owned Windows directory-rename failure")

    monkeypatch.setattr(Path, "rename", unavailable_rename)
    result = api().prepare_references(catalog, tmp_path / "batch", fetch=replies.__getitem__)
    assert result["reference_count"] == 1
    assert api().verify_references(catalog, tmp_path / "batch") == result


def test_reference_patch_preserves_missing_eof_newline(tmp_path):
    catalog, _ = owned_catalog()
    _, replies = owned_responses(
        source_contents={"buggy": b"x = 1\n# end", "fixed": b"x = 2\n# end"}
    )
    output = tmp_path / "batch"
    api().prepare_references(catalog, output, fetch=replies.__getitem__)
    assert (output / "cases/os_demo_7/gold.patch").read_text(encoding="utf-8") == (
        "--- a/src/demo/__init__.py\n+++ b/src/demo/__init__.py\n@@ -1,2 +1,2 @@\n"
        "-x = 1\n+x = 2\n # end\n\\ No newline at end of file\n"
    )
