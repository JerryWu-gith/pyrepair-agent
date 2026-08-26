from access import can_manage_users


def test_only_active_admin_can_manage_users() -> None:
    assert can_manage_users(is_active=False, is_admin=False) is False
    assert can_manage_users(is_active=True, is_admin=False) is False
    assert can_manage_users(is_active=True, is_admin=True) is True
    assert can_manage_users(is_active=False, is_admin=True) is False
