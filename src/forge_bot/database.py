from typing import Any

import bcrypt
import psycopg
from psycopg.rows import dict_row

from .config import get_settings
from .roles import is_admin_role


def verify_password(password: str, hash_db: str) -> bool:
    """Compare a plain password with the stored bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hash_db.encode("utf-8"))


def conect_db() -> Any | None:
    """Open a PostgreSQL connection using validated application settings.

    Returns:
        A psycopg connection when the database is reachable, otherwise None.
    """
    settings = get_settings()
    try:
        connection = psycopg.connect(
            host=settings.db_host,
            user=settings.db_user,
            password=settings.db_password,
            dbname=settings.db_name,
            port=settings.db_port,
            row_factory=dict_row,
        )
        return connection
    except psycopg.Error as err:
        print(f"Error connecting to the database: {err}")
        return None


def verify_user(telegram_id: int) -> bool:
    """Check whether a Telegram user is linked to an authenticated account."""
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def get_user_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    """Return the authenticated user linked to a Telegram ID, if any."""
    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, role FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            user: dict[str, Any] | None = cursor.fetchone()
            return user
    finally:
        conn.close()


def get_user_role_by_telegram_id(telegram_id: int) -> str | None:
    """Return the stored role for a logged-in Telegram user."""
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        return None
    role = user.get("role")
    return role if isinstance(role, str) else None


def is_admin(telegram_id: int) -> bool:
    """Check whether the logged-in Telegram user has the admin role."""
    return is_admin_role(get_user_role_by_telegram_id(telegram_id))


def login_user(username: str, password: str, telegram_id: int) -> bool:
    """Validate credentials and link the Telegram ID to the database user."""
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, password FROM users WHERE username = %s",
                (username,),
            )
            user = cursor.fetchone()

            if not user or not verify_password(password, user["password"]):
                return False

            cursor.execute(
                "UPDATE users SET telegram_id = %s WHERE id = %s",
                (telegram_id, user["id"]),
            )
            conn.commit()
            return True
    finally:
        conn.close()


def logout_user(telegram_id: int) -> bool:
    """Remove the Telegram ID link so the user must log in again later."""
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET telegram_id = NULL WHERE telegram_id = %s",
                (telegram_id,),
            )
            conn.commit()
            affected_rows = int(cursor.rowcount or 0)
            return affected_rows > 0
    finally:
        conn.close()


def status_user(telegram_id: int) -> dict[str, Any] | None:
    """Return the logged-in username and role for a Telegram ID, if one exists."""
    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT username, role FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            user: dict[str, Any] | None = cursor.fetchone()
            return user
    finally:
        conn.close()
