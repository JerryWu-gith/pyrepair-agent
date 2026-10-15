import pytest
from shipping import shipping_fee

def test_contract():
    assert shipping_fee(urgent=True, weight_kg=0) == 15
    assert shipping_fee(urgent=True, weight_kg=7) == 15
    assert shipping_fee(urgent=False, weight_kg=20) == 5

def test_preserved():
    assert shipping_fee(urgent=False, weight_kg=0) == 5
