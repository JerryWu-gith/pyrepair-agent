import pytest
from booleans import parse_bool

def test_contract():
    assert parse_bool("FALSE") is False
    assert parse_bool(" True ") is True
    assert parse_bool("\tfalse\n") is False

def test_preserved():
    assert parse_bool("true") is True
