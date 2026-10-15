import pytest
from access import can_manage_users

def test_contract():
    assert can_manage_users(is_active=True, is_admin=False) is False
    assert can_manage_users(is_active=False, is_admin=True) is False
    assert can_manage_users(is_active=False, is_admin=False) is False

def test_repeat():
    for _ in range(8):
        assert can_manage_users(is_active=True, is_admin=True) is True

def test_preserved():
    assert can_manage_users(is_active=True, is_admin=True) is True
