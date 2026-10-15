import pytest
from settings import require_setting, MissingSettingError

def test_contract():
    with pytest.raises(MissingSettingError, match="host"):
        require_setting({}, "host")
    assert require_setting({"x": ""}, "x") == ""
    assert require_setting({"port": "80"}, "port") == "80"

def test_preserved():
    config = {"x": "value"}
    assert require_setting(config, "x") == "value"
    assert config == {"x": "value"}
