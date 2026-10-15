import pytest
from records import parse_record_id, RecordFormatError

def test_contract():
    with pytest.raises(RecordFormatError, match="bad-id"):
        parse_record_id("bad-id")
    assert parse_record_id("-5") == -5
    assert parse_record_id("0") == 0

def test_preserved():
    assert parse_record_id("12") == 12
