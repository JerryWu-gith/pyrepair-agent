import pytest
from orders import Order

def test_contract():
    order = Order()
    order.ship()
    assert order.history == ["paid", "shipped"]
    order.ship()
    assert order.history == ["paid", "shipped", "shipped"]
    assert order.status == "shipped"

def test_preserved():
    assert Order().history == ["paid"]
