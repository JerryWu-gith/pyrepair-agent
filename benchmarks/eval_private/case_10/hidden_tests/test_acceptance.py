import pytest
from cart import Cart

def test_contract():
    cart = Cart()
    cart.add(2)
    assert cart.item_count == 2
    cart.add(3)
    assert cart.item_count == 5
    cart.add(0)
    assert cart.item_count == 5

def test_preserved():
    assert Cart().item_count == 0
