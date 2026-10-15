import pytest
from datetime import date
from dates import parse_display_date

def test_contract():
    assert parse_display_date("13-02-2024") == date(2024, 2, 13)
    assert parse_display_date("03-04-2026") == date(2026, 4, 3)
    assert parse_display_date("29-02-2024") == date(2024, 2, 29)

def test_preserved():
    with pytest.raises(ValueError):
        parse_display_date("32-01-2026")
