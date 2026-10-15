import pytest
from pagination import is_valid_page

def test_contract():
    assert is_valid_page(1, 1) is True
    assert is_valid_page(0, 3) is False
    assert is_valid_page(4, 3) is False

def test_preserved():
    assert is_valid_page(1, 0) is False
