import pytest
from settings import MissingSettingError, require_setting


def test_existing_setting_is_returned() -> None:
    assert require_setting({"region": "cn"}, "region") == "cn"


def test_missing_setting_uses_domain_error() -> None:
    with pytest.raises(MissingSettingError, match="timezone"):
        require_setting({}, "timezone")
