from enum import Enum


class UserRole(str, Enum):
    """Supported user roles stored in the users table."""

    ADMIN = "admin"
    PROFESSIONAL = "professional"
    USER = "user"


def is_admin_role(role: str | None) -> bool:
    """Return whether a stored role grants admin permissions."""
    return role == UserRole.ADMIN.value
