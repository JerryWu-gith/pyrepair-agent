"""Merge layered application settings."""


def _update(target, overrides):
    for key, value in overrides.items():
        if not value:
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _update(target[key], value)
        else:
            target[key] = value


def merge_config(defaults, overrides):
    result = dict(defaults)
    _update(result, overrides)
    return result
