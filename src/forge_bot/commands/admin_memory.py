from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.config import get_settings
from forge_bot.database import conect_db

from .auth_guard import admin_required

ADMIN_USERS_USAGE = "/admin_users [limit]"
ADMIN_MEMORY_USAGE = (
    "/admin_memory <user_id|tg:telegram_id|email:value|username:value> [profile_id]"
)
MAX_TELEGRAM_MESSAGE_CHARS = 3800
DEFAULT_USER_LIMIT = 20
MAX_USER_LIMIT = 50
RECENT_MESSAGE_LIMIT = 8
DAILY_LOG_LIMIT = 3


@admin_required
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List users with identifiers that can be passed to /admin_memory."""
    if not update.message:
        return

    limit = _parse_limit(context.args or ())
    if limit is None:
        await update.message.reply_text(f"Usage:\n{ADMIN_USERS_USAGE}")
        return

    users = list_admin_users(limit=limit)
    if users is None:
        await update.message.reply_text("Could not load users right now.")
        return
    if not users:
        await update.message.reply_text("No users found.")
        return

    lines = ["Users", ""]
    for user in users:
        lines.append(
            " ".join(
                part
                for part in (
                    f"id={user.get('id')}",
                    f"tg={user.get('telegram_id')}",
                    f"role={user.get('role')}",
                    f"username={user.get('username')}",
                    f"email={user.get('email')}" if user.get("email") else "",
                )
                if part
            )
        )
    lines.extend(("", f"Use: {ADMIN_MEMORY_USAGE}"))
    await _reply_chunks(update, "\n".join(lines))


@admin_required
async def admin_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return a sectioned memory snapshot for one user."""
    if not update.message:
        return

    args = [arg.strip() for arg in (context.args or []) if arg.strip()]
    if not args or len(args) > 2:
        await update.message.reply_text(f"Usage:\n{ADMIN_MEMORY_USAGE}")
        return

    profile_id = args[1] if len(args) == 2 else get_settings().bot_profile
    report = build_admin_memory_report(args[0], profile_id=profile_id)
    await _reply_chunks(update, report)


def list_admin_users(*, limit: int) -> list[Mapping[str, Any]] | None:
    connection = conect_db()
    if connection is None:
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, telegram_id, username, email, role, created_at, deleted_at
                FROM users
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return list(cursor.fetchall())
    finally:
        connection.close()


def build_admin_memory_report(identifier: str, *, profile_id: str) -> str:
    user = resolve_admin_user(identifier)
    if user is None:
        return (
            "User not found.\n\n"
            f"Usage:\n{ADMIN_MEMORY_USAGE}\n\n"
            "Examples:\n/admin_memory 7\n/admin_memory tg:123456\n"
            "/admin_memory email:person@example.com nutrition"
        )

    snapshot = load_user_memory_snapshot(user_id=int(user["id"]), profile_id=profile_id)
    if snapshot is None:
        return "Could not load user memory right now."

    return _format_memory_report(user=user, profile_id=profile_id, snapshot=snapshot)


def resolve_admin_user(identifier: str) -> Mapping[str, Any] | None:
    field, value = _parse_user_identifier(identifier)
    numeric_value = (
        _parse_int_identifier(value) if field in {"id", "telegram_id"} else None
    )
    if field in {"id", "telegram_id"} and numeric_value is None:
        return None
    connection = conect_db()
    if connection is None:
        return None
    try:
        with connection.cursor() as cursor:
            if field == "id":
                cursor.execute(
                    """
                    SELECT id, telegram_id, username, email, role, created_at,
                           deleted_at
                    FROM users
                    WHERE id = %s
                    """,
                    (numeric_value,),
                )
            elif field == "telegram_id":
                cursor.execute(
                    """
                    SELECT id, telegram_id, username, email, role, created_at,
                           deleted_at
                    FROM users
                    WHERE telegram_id = %s
                    """,
                    (numeric_value,),
                )
            elif field == "email":
                cursor.execute(
                    """
                    SELECT id, telegram_id, username, email, role, created_at,
                           deleted_at
                    FROM users
                    WHERE lower(email) = lower(%s)
                    """,
                    (value,),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, telegram_id, username, email, role, created_at,
                           deleted_at
                    FROM users
                    WHERE username = %s
                    """,
                    (value,),
                )
            row = cursor.fetchone()
            return row if isinstance(row, Mapping) else None
    finally:
        connection.close()


def _parse_int_identifier(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def load_user_memory_snapshot(
    *,
    user_id: int,
    profile_id: str,
) -> dict[str, Any] | None:
    connection = conect_db()
    if connection is None:
        return None
    try:
        with connection.cursor() as cursor:
            return {
                "daily_logs": _fetch_daily_logs(cursor, user_id, profile_id),
                "compact_memory": _fetch_compact_memory(cursor, user_id, profile_id),
                "langchain_messages": _fetch_langchain_messages(
                    cursor,
                    user_id,
                    profile_id,
                ),
                "legacy_messages": _fetch_legacy_messages(cursor, user_id, profile_id),
                "db_active_plan": _fetch_db_active_plan(cursor, user_id),
            }
    finally:
        connection.close()


def _fetch_daily_logs(
    cursor: Any,
    user_id: int,
    profile_id: str,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        SELECT log_date, situation_key, meals, notes, updated_at
        FROM nutrition_daily_logs
        WHERE user_id = %s
          AND bot_profile_id = %s
        ORDER BY log_date DESC
        LIMIT %s
        """,
        (user_id, profile_id, DAILY_LOG_LIMIT),
    )
    return list(cursor.fetchall())


def _fetch_compact_memory(
    cursor: Any,
    user_id: int,
    profile_id: str,
) -> Mapping[str, Any] | None:
    cursor.execute(
        """
        SELECT summary, source_message_count, compaction_version, updated_at
        FROM user_memory_summaries
        WHERE user_id = %s
          AND bot_profile_id = %s
          AND deleted_at IS NULL
        """,
        (user_id, profile_id),
    )
    row = cursor.fetchone()
    return row if isinstance(row, Mapping) else None


def _fetch_langchain_messages(
    cursor: Any,
    user_id: int,
    profile_id: str,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        SELECT h.created_at, h.message
        FROM langchain_chat_sessions s
        JOIN langchain_chat_history h ON h.session_id = s.session_id
        WHERE s.user_id = %s
          AND s.bot_profile_id = %s
        ORDER BY h.created_at DESC, h.id DESC
        LIMIT %s
        """,
        (user_id, profile_id, RECENT_MESSAGE_LIMIT),
    )
    rows = list(cursor.fetchall())
    rows.reverse()
    return rows


def _fetch_legacy_messages(
    cursor: Any,
    user_id: int,
    profile_id: str,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        SELECT role, content, created_at
        FROM conversation_messages
        WHERE user_id = %s
          AND bot_profile_id = %s
          AND deleted_at IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (user_id, profile_id, RECENT_MESSAGE_LIMIT),
    )
    rows = list(cursor.fetchall())
    rows.reverse()
    return rows


def _fetch_db_active_plan(cursor: Any, user_id: int) -> Mapping[str, Any] | None:
    cursor.execute("SELECT to_regclass('nutrition_plans') AS table_name")
    table_row = cursor.fetchone()
    if not table_row or table_row.get("table_name") is None:
        return None
    cursor.execute(
        """
        SELECT id, status, created_at, updated_at
        FROM nutrition_plans
        WHERE user_id = %s
        ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                 updated_at DESC NULLS LAST,
                 created_at DESC NULLS LAST
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    return row if isinstance(row, Mapping) else None


def _format_memory_report(
    *,
    user: Mapping[str, Any],
    profile_id: str,
    snapshot: Mapping[str, Any],
) -> str:
    sections = [
        "User memory",
        _format_user(user, profile_id),
        _format_db_active_plan(snapshot.get("db_active_plan")),
        _format_daily_logs(snapshot.get("daily_logs")),
        _format_compact_memory(snapshot.get("compact_memory")),
        _format_messages(
            "LangChain recent messages",
            snapshot.get("langchain_messages"),
        ),
        _format_messages("Legacy recent messages", snapshot.get("legacy_messages")),
    ]
    return "\n\n".join(section for section in sections if section)


def _format_user(user: Mapping[str, Any], profile_id: str) -> str:
    return "\n".join(
        (
            f"Profile: {profile_id}",
            f"User id: {user.get('id')}",
            f"Telegram id: {user.get('telegram_id')}",
            f"Username: {user.get('username')}",
            f"Email: {user.get('email') or '-'}",
            f"Role: {user.get('role')}",
        )
    )


def _format_db_active_plan(value: object) -> str:
    if not isinstance(value, Mapping) or not value:
        return "DB active plan: not available yet"
    return "\n".join(
        (
            "DB active plan:",
            f"- id: {value.get('id')}",
            f"- status: {value.get('status')}",
            f"- updated_at: {value.get('updated_at')}",
        )
    )


def _format_daily_logs(value: object) -> str:
    logs = value if isinstance(value, list) else []
    if not logs:
        return "Daily logs: none"
    sections = ["Daily logs:"]
    for log in logs:
        if not isinstance(log, Mapping):
            continue
        sections.append(
            "\n".join(
                (
                    f"- date: {log.get('log_date')}",
                    f"  tipo_dia: {log.get('situation_key') or '-'}",
                    f"  meals: {_compact_json(log.get('meals'))}",
                    f"  notes: {_compact_json(log.get('notes'))}",
                )
            )
        )
    return "\n".join(sections)


def _format_compact_memory(value: object) -> str:
    if not isinstance(value, Mapping) or not value:
        return "Compact memory: none"
    return "\n".join(
        (
            "Compact memory:",
            f"- source_message_count: {value.get('source_message_count')}",
            f"- updated_at: {value.get('updated_at')}",
            f"- summary: {_short(value.get('summary'), 1200)}",
        )
    )


def _format_messages(title: str, value: object) -> str:
    messages = value if isinstance(value, list) else []
    if not messages:
        return f"{title}: none"
    lines = [f"{title}:"]
    for row in messages:
        if not isinstance(row, Mapping):
            continue
        role, content = _message_role_content(row)
        lines.append(f"- {role}: {_short(content, 260)}")
    return "\n".join(lines)


def _message_role_content(row: Mapping[str, Any]) -> tuple[str, str]:
    if "message" not in row:
        return str(row.get("role") or "unknown"), str(row.get("content") or "")
    message = row.get("message")
    if not isinstance(message, Mapping):
        return "unknown", str(message or "")
    message_type = str(message.get("type") or "")
    role = "assistant" if message_type in {"ai", "assistant"} else "user"
    data = message.get("data")
    if isinstance(data, Mapping):
        content = data.get("content")
    else:
        content = message.get("content")
    return role, str(content or "")


def _parse_user_identifier(identifier: str) -> tuple[str, str]:
    value = identifier.strip()
    lowered = value.lower()
    if lowered.startswith(("tg:", "telegram:")):
        return "telegram_id", value.split(":", 1)[1].strip()
    if lowered.startswith("email:"):
        return "email", value.split(":", 1)[1].strip()
    if lowered.startswith("username:"):
        return "username", value.split(":", 1)[1].strip()
    if lowered.startswith("id:"):
        return "id", value.split(":", 1)[1].strip()
    return "id", value


def _parse_limit(args: Sequence[str]) -> int | None:
    if not args:
        return DEFAULT_USER_LIMIT
    if len(args) > 1:
        return None
    try:
        limit = int(args[0])
    except ValueError:
        return None
    if limit < 1:
        return None
    return min(limit, MAX_USER_LIMIT)


async def _reply_chunks(update: Update, text: str) -> None:
    if not update.message:
        return
    for chunk in _chunks(text, MAX_TELEGRAM_MESSAGE_CHARS):
        await update.message.reply_text(chunk)


def _chunks(text: str, max_chars: int) -> Iterable[str]:
    remaining = text
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n\n", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars
        yield remaining[:split_at].strip()
        remaining = remaining[split_at:].strip()
    if remaining:
        yield remaining


def _compact_json(value: object) -> str:
    if value in (None, {}, []):
        return "-"
    return _short(json.dumps(value, ensure_ascii=False, sort_keys=True), 900)


def _short(value: object, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
