import pytest
from discounts import discount_rate

def test_contract():
    assert discount_rate("student") == .10
    assert discount_rate("regular") == .05
    assert discount_rate("") == .05

def test_preserved():
    assert discount_rate("vip") == .20
