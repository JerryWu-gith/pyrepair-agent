from access import can_manage_users


def test_inactive_non_admin_cannot_manage_users() -> None:
    assert can_manage_users(is_active=False, is_admin=False) is False


def test_active_non_admin_cannot_manage_users() -> None:
    assert can_manage_users(is_active=True, is_admin=False) is False
