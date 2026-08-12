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
