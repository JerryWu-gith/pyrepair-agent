from datetime import date

from dates import parse_display_date


def test_symmetric_display_date_is_parsed() -> None:
    assert parse_display_date("01-01-2026") == date(2026, 1, 1)


def test_day_first_display_date_is_parsed() -> None:
    assert parse_display_date("31-08-2026") == date(2026, 8, 31)
