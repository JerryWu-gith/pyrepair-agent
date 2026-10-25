import json
import shutil

import pytest

from tests.test_opensource_assembly import CASE_ID, prepare_handwritten_source


def test_cli_assembles_verified_cache_without_network_or_execution(tmp_path, monkeypatch, capsys):
    from benchmarks import prepare_opensource_cases as cli
    from benchmarks.evaluation import opensource_assets

    cache = tmp_path / "downloads"
    prepared = prepare_handwritten_source(tmp_path / "fixture", monkeypatch)
    shutil.copytree(prepared, cache / CASE_ID)
    monkeypatch.setattr(
        opensource_assets,
        "fetch_bytes",
        lambda *a, **k: pytest.fail("assemble-only cannot download"),
    )
    destination = tmp_path / "bank"
    code = cli.main(
        [
            "--case",
            CASE_ID,
            "--cache",
            str(cache),
            "--destination",
            str(destination),
            "--assemble-only",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "assets_prepared" in output
    assert "offline_validated" not in output
    manifest = json.loads((destination / "manifest_opensource_v1.json").read_text())
    assert [case["id"] for case in manifest["cases"]] == [CASE_ID]


def test_cli_refuses_existing_manifest_before_downloading(tmp_path, monkeypatch, capsys):
    from benchmarks import prepare_opensource_cases as cli

    destination = tmp_path / "bank"
    destination.mkdir()
    manifest = destination / "manifest_opensource_v1.json"
    manifest.write_bytes(b"preserve old evidence")
    monkeypatch.setattr(cli, "prepare_source", lambda *a, **k: pytest.fail("no network allowed"))
    code = cli.main(["--cache", str(tmp_path / "downloads"), "--destination", str(destination)])
    assert code == 2
    assert manifest.read_bytes() == b"preserve old evidence"
    assert not (tmp_path / "downloads").exists()
    assert "overwrite" in capsys.readouterr().err


def test_cli_requires_explicit_cache_and_rejects_unknown_task():
    from benchmarks import prepare_opensource_cases as cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--case", "arbitrary-url"])
    assert exc.value.code == 2
