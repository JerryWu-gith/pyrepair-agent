import pytest
from records import RecordFormatError, parse_record_id


def test_numeric_record_id_is_parsed() -> None:
    assert parse_record_id("42") == 42


def test_invalid_record_id_uses_domain_error() -> None:
    with pytest.raises(RecordFormatError, match="abc"):
        parse_record_id("abc")
