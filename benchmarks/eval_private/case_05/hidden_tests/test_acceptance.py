import pytest
from inventory import can_fulfill

def test_contract():
    assert can_fulfill(0, 0) is True
    assert can_fulfill(5, 6) is False
    assert can_fulfill(0, 1) is False

def test_preserved():
    assert can_fulfill(3, 1) is True
