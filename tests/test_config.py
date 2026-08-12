import pytest

from pyrepair.config import ConfigError, load_config


def test_load_config_uses_flash_by_default(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("PYREPAIR_MODEL", raising=False)

    config = load_config()

    assert config.model == "deepseek-v4-flash"
    assert config.api_key == "test-key"


def test_load_config_rejects_unknown_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("PYREPAIR_MODEL", "unknown")

    with pytest.raises(ConfigError, match="PYREPAIR_MODEL"):
        load_config()


def test_load_config_accepts_cli_model_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("PYREPAIR_MODEL", "deepseek-v4-flash")

    config = load_config(model_override="deepseek-v4-pro")

    assert config.model == "deepseek-v4-pro"


def test_load_config_can_skip_api_key_for_dry_run(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    config = load_config(require_api_key=False)

    assert config.api_key == ""
