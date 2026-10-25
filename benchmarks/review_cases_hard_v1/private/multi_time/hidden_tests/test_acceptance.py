from datetime import UTC, datetime

from parsing import parse_timestamp
from service import normalize


def test_contract():
    assert normalize("2026-01-01T01:00:00+08:00") == "2025-12-31T17:00:00Z"
    assert normalize("2026-10-01T23:00:00-05:00") == "2026-10-02T04:00:00Z"
    assert normalize("2026-02-03T12:34:56Z") == "2026-02-03T12:34:56Z"


def test_preserved():
    assert parse_timestamp("2026-01-01T00:00:00+00:00") == datetime(2026, 1, 1, tzinfo=UTC)


def test_parser_returns_utc():
    from datetime import timedelta

    parsed = parse_timestamp("2026-01-01T05:30:00+05:30")
    assert parsed.utcoffset() == timedelta(0)
    assert parsed == datetime(2026, 1, 1, tzinfo=UTC)


def test_fractional_seconds():
    assert normalize("2026-02-03T12:34:56.987Z") == "2026-02-03T12:34:56Z"
