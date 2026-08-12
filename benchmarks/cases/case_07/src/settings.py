class MissingSettingError(LookupError):
    pass


def require_setting(config: dict[str, str], key: str) -> str:
    return config[key]
