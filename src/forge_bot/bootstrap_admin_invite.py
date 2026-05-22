"""Bootstrap helpers for creating the first admin invite in Docker."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from os import environ

import psycopg

from . import database

logger = logging.getLogger(__name__)

BOOTSTRAP_ADMIN_EMAIL = "BOOTSTRAP_ADMIN_EMAIL"
BOOTSTRAP_BOT_USERNAME = "BOOTSTRAP_BOT_USERNAME"
BOOTSTRAP_ADMIN_INVITE_TTL_HOURS = "BOOTSTRAP_ADMIN_INVITE_TTL_HOURS"
BOOTSTRAP_ADMIN_INVITE_FORCE = "BOOTSTRAP_ADMIN_INVITE_FORCE"


@dataclass(frozen=True)
class BootstrapAdminInviteResult:
    status: str
    invite_link: str | None = None
    app_link: str | None = None
    reason: str | None = None


def bootstrap_admin_invite_from_env(
    env: Mapping[str, str] = environ,
) -> BootstrapAdminInviteResult:
    """Create the first admin invite when bootstrap env vars are configured."""
    email = database.normalize_invite_email(env.get(BOOTSTRAP_ADMIN_EMAIL, ""))
    if email is None:
        return BootstrapAdminInviteResult(
            "skipped",
            reason=f"{BOOTSTRAP_ADMIN_EMAIL} is not set",
        )

    bot_username = _clean(env.get(BOOTSTRAP_BOT_USERNAME))
    if bot_username is None:
        return BootstrapAdminInviteResult(
            "skipped",
            reason=f"{BOOTSTRAP_BOT_USERNAME} is not set",
        )

    ttl_hours = _parse_positive_int(env.get(BOOTSTRAP_ADMIN_INVITE_TTL_HOURS))
    force = _parse_bool(env.get(BOOTSTRAP_ADMIN_INVITE_FORCE))
    return bootstrap_admin_invite(
        email=email,
        bot_username=bot_username,
        ttl_hours=ttl_hours,
        force=force,
    )


def bootstrap_admin_invite(
    *,
    email: str,
    bot_username: str,
    ttl_hours: int | None = None,
    force: bool = False,
) -> BootstrapAdminInviteResult:
    """Create an admin invite unless an admin or pending invite already exists."""
    if _has_active_admin_user():
        return BootstrapAdminInviteResult(
            "skipped",
            reason="an active admin user already exists",
        )

    if not force and _has_pending_admin_invite(email):
        return BootstrapAdminInviteResult(
            "skipped",
            reason=(
                "an unused admin invite already exists for this email; set "
                f"{BOOTSTRAP_ADMIN_INVITE_FORCE}=true to create another"
            ),
        )

    invite = database.create_invite_token(
        role="admin",
        email=email,
        ttl_hours=ttl_hours,
        bot_username=bot_username,
    )
    if invite is None:
        return BootstrapAdminInviteResult(
            "error",
            reason="database connection failed",
        )

    return BootstrapAdminInviteResult(
        "created",
        invite_link=invite.invite_link,
        app_link=invite.app_link,
    )


def _has_active_admin_user() -> bool:
    conn = database.conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id
                FROM users
                WHERE role = 'admin'
                  AND deleted_at IS NULL
                LIMIT 1
                """)
            return cursor.fetchone() is not None
    except psycopg.Error:
        logger.exception("bootstrap_admin_user_check_failed")
        return False
    finally:
        conn.close()


def _has_pending_admin_invite(email: str) -> bool:
    conn = database.conect_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM invite_tokens
                WHERE role = 'admin'
                  AND lower(email) = lower(%s)
                  AND used_at IS NULL
                  AND expires_at > CURRENT_TIMESTAMP
                LIMIT 1
                """,
                (email,),
            )
            return cursor.fetchone() is not None
    except psycopg.Error:
        logger.exception("bootstrap_admin_invite_check_failed email=%s", email)
        return False
    finally:
        conn.close()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_positive_int(value: str | None) -> int | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        parsed = int(cleaned)
    except ValueError:
        logger.warning(
            "Ignoring invalid %s value: %s",
            BOOTSTRAP_ADMIN_INVITE_TTL_HOURS,
            value,
        )
        return None
    if parsed <= 0:
        logger.warning(
            "Ignoring non-positive %s value: %s",
            BOOTSTRAP_ADMIN_INVITE_TTL_HOURS,
            value,
        )
        return None
    return parsed


def _parse_bool(value: str | None) -> bool:
    cleaned = _clean(value)
    if cleaned is None:
        return False
    return cleaned.lower() in {"1", "true", "yes", "on"}


def _report_result(result: BootstrapAdminInviteResult) -> None:
    if result.status == "created":
        print("Bootstrap admin invite created.")
        if result.invite_link:
            print(f"Invite link: {result.invite_link}")
        if result.app_link:
            print(f"Telegram app link: {result.app_link}")
        return

    if result.status == "skipped":
        print(f"Bootstrap admin invite skipped: {result.reason}.")
        return

    print(f"Bootstrap admin invite failed: {result.reason}.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _report_result(bootstrap_admin_invite_from_env())


if __name__ == "__main__":
    main()
