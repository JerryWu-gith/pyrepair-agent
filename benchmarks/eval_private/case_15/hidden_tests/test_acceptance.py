import pytest
from money import dollars_to_cents

def test_contract():
    assert dollars_to_cents("0.29") == 29
    assert dollars_to_cents("1.01") == 101
    assert dollars_to_cents("100.99") == 10099

def test_preserved():
    assert dollars_to_cents("0") == 0
