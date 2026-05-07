import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import bcrypt
import psycopg
from psycopg.rows import dict_row

from .config import get_settings

# The time to live for invite tokens, in hours.
DEFAULT_INVITE_TOKEN_TTL_HOURS = 24
INVITE_TOKEN_BYTES = 32
VALID_INVITE_ROLES = frozenset({"user", "admin", "professional"})


@dataclass(frozen=True)
class InviteToken:
    raw_token: str
    token_hash: str
    role: str
    expires_at: datetime
    invite_link: str | None = None
    app_link: str | None = None


@dataclass(frozen=True)
class InviteRedemption:
    status: str
    username: str | None = None
    role: str | None = None


def verify_password(password: str, hash_db: str) -> bool:
    """Compare a plain password with the stored bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hash_db.encode("utf-8"))


def generate_invite_token() -> str:
    """Generate a high-entropy token safe for Telegram deep links."""
    return secrets.token_urlsafe(INVITE_TOKEN_BYTES)


def hash_invite_token(raw_token: str) -> str:
    """Hash an invite token before it is persisted or looked up."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def build_invite_link(bot_username: str, raw_token: str) -> str:
    """Build the Telegram deep link that sends /start <token> to the bot."""
    clean_username = bot_username.strip().removeprefix("@")
    if not clean_username:
        raise ValueError("Bot username is required to build an invite link")

    return f"https://t.me/{clean_username}?start={quote(raw_token, safe='')}"


def build_telegram_app_link(bot_username: str, raw_token: str) -> str:
    """Build a Telegram app URI that bypasses the t.me preview page."""
    clean_username = bot_username.strip().removeprefix("@")
    if not clean_username:
        raise ValueError("Bot username is required to build an app link")

    return f"tg://resolve?domain={clean_username}&start={quote(raw_token, safe='')}"


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

            if not user or not user["password"]:
                return False

            if not verify_password(password, user["password"]):
                return False

            cursor.execute(
                "UPDATE users SET telegram_id = %s WHERE id = %s",
                (telegram_id, user["id"]),
            )
            conn.commit()
            return True
    finally:
        conn.close()


def create_invite_token(
    role: str = "user",
    *,
    ttl_hours: int = DEFAULT_INVITE_TOKEN_TTL_HOURS,
    created_by_user_id: int | None = None,
    bot_username: str | None = None,
) -> InviteToken | None:
    """Create a single-use invite token and store only its hash."""
    normalized_role = role.lower()
    if normalized_role not in VALID_INVITE_ROLES:
        raise ValueError(f"Unsupported invite role: {role}")
    if ttl_hours <= 0:
        raise ValueError("Invite token TTL must be positive")

    raw_token = generate_invite_token()
    token_hash = hash_invite_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO invite_tokens (
                    token_hash,
                    role,
                    expires_at,
                    created_by_user_id
                )
                VALUES (%s, %s, %s, %s)
                """,
                (token_hash, normalized_role, expires_at, created_by_user_id),
            )
            conn.commit()
            invite_link = (
                build_invite_link(bot_username, raw_token) if bot_username else None
            )
            app_link = (
                build_telegram_app_link(bot_username, raw_token)
                if bot_username
                else None
            )
            return InviteToken(
                raw_token,
                token_hash,
                normalized_role,
                expires_at,
                invite_link,
                app_link,
            )
    finally:
        conn.close()


def redeem_invite_token(raw_token: str, telegram_id: int) -> InviteRedemption:
    """Redeem a single-use invite token and link it to the Telegram user."""
    token_hash = hash_invite_token(raw_token)
    conn = conect_db()
    if not conn:
        return InviteRedemption("db_error")

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            existing_user = cursor.fetchone()
            if existing_user:
                return InviteRedemption(
                    "already_linked",
                    username=existing_user["username"],
                )

            cursor.execute(
                """
                SELECT id, role, expires_at, used_at
                FROM invite_tokens
                WHERE token_hash = %s
                FOR UPDATE
                """,
                (token_hash,),
            )
            invite = cursor.fetchone()
            if not invite:
                return InviteRedemption("invalid")

            if invite["used_at"] is not None:
                return InviteRedemption("used")

            expires_at = invite["expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                return InviteRedemption("expired")

            username = f"telegram_{telegram_id}_{invite['id']}"
            cursor.execute(
                """
                INSERT INTO users (username, password, telegram_id, role)
                VALUES (%s, NULL, %s, %s)
                ON CONFLICT (telegram_id) DO NOTHING
                RETURNING id, username
                """,
                (username, telegram_id, invite["role"]),
            )
            user = cursor.fetchone()
            if not user:
                conn.rollback()
                return InviteRedemption("already_linked")

            cursor.execute(
                """
                UPDATE invite_tokens
                SET used_at = CURRENT_TIMESTAMP,
                    used_by_user_id = %s
                WHERE id = %s
                """,
                (user["id"], invite["id"]),
            )
            conn.commit()
            return InviteRedemption(
                "success",
                username=user["username"],
                role=invite["role"],
            )
    except psycopg.Error:
        conn.rollback()
        return InviteRedemption("db_error")
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
    """Return the logged-in username for a Telegram ID, if one exists."""
    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT username FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            user: dict[str, Any] | None = cursor.fetchone()
            return user
    finally:
        conn.close()
