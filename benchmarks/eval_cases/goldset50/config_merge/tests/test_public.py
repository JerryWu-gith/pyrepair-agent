from config_merge import merge_config


def test_nested_defaults_are_not_mutated():
    defaults = {"server": {"host": "localhost", "port": 8000}}
    overrides = {"server": {"port": 9000}}
    result = merge_config(defaults, overrides)
    assert result == {"server": {"host": "localhost", "port": 9000}}
    assert defaults == {"server": {"host": "localhost", "port": 8000}}
    assert overrides == {"server": {"port": 9000}}


def test_nonempty_values_and_unmentioned_keys_are_preserved():
    result = merge_config({"mode": "dev", "workers": 2}, {"mode": "prod"})
    assert result == {"mode": "prod", "workers": 2}
