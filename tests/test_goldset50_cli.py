"""CLI preparation is real data handling; credentials are only owned fixtures."""

import importlib
import importlib.util
import sys
from types import SimpleNamespace

import pytest

from tests.test_goldset50_dataset import materialized_selection


def cli():
    name = "benchmarks.run_goldset50"
    assert importlib.util.find_spec(name) is not None, "goldset entry missing"
    return importlib.import_module(name)


def test_assemble_cli_creates_only_verified_dataset_without_credential_access(
    tmp_path, capsys, monkeypatch
):
    module = cli()
    monkeypatch.setattr(
        module, "_configured_credential", lambda: pytest.fail("offline route read key")
    )
    source = materialized_selection(tmp_path)
    output = tmp_path / "unified"
    assert module.main(["assemble", "--manifest", str(source), "--output", str(output)]) == 0
    assert (output / "dataset.json").is_file()
    assert "API calls=0" in capsys.readouterr().out


def test_credential_getter_reads_only_configured_user_key_without_output(monkeypatch, capsys):
    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def query(key, name):
        assert name == "DEEPSEEK_API_KEY"
        return "owned-not-real-credential", 1

    fake = SimpleNamespace(
        HKEY_CURRENT_USER=1, OpenKey=lambda root, path: Key(), QueryValueEx=query
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    module = cli()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "owned-process-fallback")
    assert module._configured_credential() == "owned-not-real-credential"
    assert capsys.readouterr().out == ""


def test_missing_credential_does_not_create_a_network_probe(monkeypatch):
    def missing(*args):
        raise FileNotFoundError("owned missing registry key")

    monkeypatch.setitem(
        sys.modules, "winreg", SimpleNamespace(HKEY_CURRENT_USER=1, OpenKey=missing)
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="credential"):
        cli()._configured_credential()
