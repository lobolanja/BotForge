import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any
from urllib.parse import quote

import bcrypt
import psycopg
from psycopg.rows import dict_row

from .config import get_settings
from .roles import is_admin_role

# The time to live for invite tokens, in hours.
DEFAULT_INVITE_TOKEN_TTL_HOURS = 24
INVITE_TOKEN_BYTES = 32
VALID_INVITE_ROLES = frozenset({"user", "admin"})
RESERVED_INVITE_ROLES = frozenset({"professional"})


@dataclass(frozen=True)
class InviteToken:
    raw_token: str
    token_hash: str
    role: str
    email: str
    expires_at: datetime
    invite_link: str | None = None
    app_link: str | None = None


@dataclass(frozen=True)
class InviteRedemption:
    status: str
    username: str | None = None
    role: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class PolicyVersions:
    policy_version: str
    privacy_notice_version: str


def current_policy_versions() -> PolicyVersions:
    """Return the policy versions users must accept before protected use."""
    settings = get_settings()
    return PolicyVersions(
        settings.bot_policy_version,
        settings.bot_privacy_notice_version,
    )


def generate_invite_token() -> str:
    """Generate a high-entropy token safe for Telegram deep links."""
    return secrets.token_urlsafe(INVITE_TOKEN_BYTES)


def hash_invite_token(raw_token: str) -> str:
    """Hash an invite token with bcrypt before storing it."""
    return bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_invite_token(raw_token: str, token_hash: str) -> bool:
    """Compare a raw invite token with a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            raw_token.encode("utf-8"),
            token_hash.encode("utf-8"),
        )
    except ValueError:
        return False


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


def normalize_invite_email(email: str) -> str | None:
    """Return a normalized invite email, or None when the input is invalid."""
    cleaned = email.strip()
    if not cleaned or any(char.isspace() for char in cleaned):
        return None

    _, parsed = parseaddr(cleaned)
    if parsed != cleaned:
        return None

    local, separator, domain = cleaned.rpartition("@")
    if separator != "@" or not local or not domain:
        return None
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None

    return cleaned.lower()


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
    """Check whether a Telegram user is linked to an internal account."""
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
    """Return the internal user linked to a Telegram ID, if any."""
    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, email, role FROM users WHERE telegram_id = %s",
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


def has_current_policy_acceptance(telegram_id: int) -> bool:
    """Check whether the Telegram user accepted the current required policy."""
    versions = current_policy_versions()
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM user_policy_acceptances upa
                JOIN users u ON u.id = upa.user_id
                WHERE u.telegram_id = %s
                  AND upa.policy_version = %s
                  AND upa.privacy_notice_version = %s
                  AND upa.accepted_at IS NOT NULL
                  AND upa.revoked_at IS NULL
                LIMIT 1
                """,
                (
                    telegram_id,
                    versions.policy_version,
                    versions.privacy_notice_version,
                ),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def accept_current_policy(telegram_id: int, source: str = "telegram") -> bool:
    """Store acceptance for the current policy versions."""
    versions = current_policy_versions()
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_policy_acceptances (
                    user_id,
                    policy_version,
                    privacy_notice_version,
                    accepted_at,
                    source
                )
                SELECT id, %s, %s, CURRENT_TIMESTAMP, %s
                FROM users
                WHERE telegram_id = %s
                ON CONFLICT (
                    user_id,
                    policy_version,
                    privacy_notice_version,
                    source
                )
                DO UPDATE SET
                    accepted_at = CURRENT_TIMESTAMP,
                    revoked_at = NULL
                """,
                (
                    versions.policy_version,
                    versions.privacy_notice_version,
                    source,
                    telegram_id,
                ),
            )
            conn.commit()
            return int(cursor.rowcount or 0) > 0
    except psycopg.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def decline_current_policy(telegram_id: int) -> bool:
    """Record that the user remains blocked by revoking current acceptance."""
    versions = current_policy_versions()
    conn = conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_policy_acceptances upa
                SET revoked_at = CURRENT_TIMESTAMP
                FROM users u
                WHERE u.id = upa.user_id
                  AND u.telegram_id = %s
                  AND upa.policy_version = %s
                  AND upa.privacy_notice_version = %s
                  AND upa.revoked_at IS NULL
                """,
                (
                    telegram_id,
                    versions.policy_version,
                    versions.privacy_notice_version,
                ),
            )
            conn.commit()
            return True
    except psycopg.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def create_invite_token(
    role: str = "user",
    *,
    email: str,
    ttl_hours: int | None = None,
    created_by_user_id: int | None = None,
    bot_username: str | None = None,
) -> InviteToken | None:
    """Create a single-use invite token and store only its hash."""
    if ttl_hours is None:
        ttl_hours = get_settings().invite_token_ttl_hours
    normalized_role = role.lower()
    if normalized_role not in VALID_INVITE_ROLES:
        raise ValueError(f"Unsupported invite role: {role}")
    normalized_email = normalize_invite_email(email)
    if normalized_email is None:
        raise ValueError(f"Invalid invite email: {email}")
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
                    email,
                    expires_at,
                    created_by_user_id
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    token_hash,
                    normalized_role,
                    normalized_email,
                    expires_at,
                    created_by_user_id,
                ),
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
                normalized_email,
                expires_at,
                invite_link,
                app_link,
            )
    finally:
        conn.close()


def redeem_invite_token(raw_token: str, telegram_id: int) -> InviteRedemption:
    """Redeem a single-use invite token and link it to the Telegram user."""
    conn = conect_db()
    if not conn:
        return InviteRedemption("db_error")

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, email FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            existing_user = cursor.fetchone()
            if existing_user:
                return InviteRedemption(
                    "already_linked",
                    username=existing_user["username"],
                    email=existing_user["email"],
                )

            cursor.execute(
                """
                SELECT id, token_hash, role, email, expires_at, used_at
                FROM invite_tokens
                FOR UPDATE
                """,
            )
            invite = next(
                (
                    row
                    for row in cursor.fetchall()
                    if verify_invite_token(raw_token, row["token_hash"])
                ),
                None,
            )
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
                INSERT INTO users (username, email, password, telegram_id, role)
                VALUES (%s, %s, NULL, %s, %s)
                ON CONFLICT (telegram_id) DO NOTHING
                RETURNING id, username, email
                """,
                (username, invite["email"], telegram_id, invite["role"]),
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
                email=user["email"],
            )
    except psycopg.Error:
        conn.rollback()
        return InviteRedemption("db_error")
    finally:
        conn.close()


def status_user(telegram_id: int) -> dict[str, Any] | None:
    """Return the linked username, email, and role for a Telegram ID, if any."""
    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT username, email, role FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            user: dict[str, Any] | None = cursor.fetchone()
            return user
    finally:
        conn.close()
