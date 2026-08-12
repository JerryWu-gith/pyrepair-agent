def can_manage_users(*, is_active: bool, is_admin: bool) -> bool:
    return is_active or is_admin
