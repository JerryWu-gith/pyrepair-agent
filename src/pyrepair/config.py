import os
from dataclasses import dataclass

ALLOWED_MODELS = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"}


class ConfigError(RuntimeError):
    """Raised when PyRepair configuration is missing or invalid."""


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    model: str
    base_url: str = "https://api.deepseek.com"
    api_timeout_seconds: float = 90.0
    pytest_timeout_seconds: float = 120.0


def load_config(
    require_api_key: bool = True,
    model_override: str | None = None,
) -> AppConfig:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    model = (
        model_override
        if model_override is not None
        else os.getenv("PYREPAIR_MODEL", "deepseek-v4-flash")
    )
    if require_api_key and not api_key:
        raise ConfigError("缺少 DEEPSEEK_API_KEY")
    if model not in ALLOWED_MODELS:
        raise ConfigError(f"PYREPAIR_MODEL 必须是 {sorted(ALLOWED_MODELS)} 之一")
    return AppConfig(api_key=api_key, model=model)
