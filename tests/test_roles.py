from forge_bot.roles import UserRole, is_admin_role


def test_admin_role_passes_admin_check() -> None:
    assert is_admin_role(UserRole.ADMIN.value)


def test_user_role_fails_admin_check() -> None:
    assert not is_admin_role(UserRole.USER.value)


def test_professional_role_fails_admin_check() -> None:
    assert not is_admin_role(UserRole.PROFESSIONAL.value)
