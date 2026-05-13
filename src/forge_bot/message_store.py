from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from telegram import Update

from .config import get_settings
from .database import conect_db

SUPPORTED_FILE_FIELDS = {
    "document": ("file_name", "mime_type", "file_size"),
    "photo": ("file_size",),
    "voice": ("mime_type", "file_size"),
    "audio": ("file_name", "mime_type", "file_size"),
    "video": ("file_name", "mime_type", "file_size"),
}


@dataclass(frozen=True)
class InboundMessage:
    telegram_update_id: int
    telegram_message_id: int
    chat_id: int
    telegram_user_id: int | None
    message_type: str
    text: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    received_at: datetime | None = None
    raw_update: dict[str, Any] | None = None


@dataclass(frozen=True)
class RecoverySummary:
    retried: int
    expired: int
    failed: int


def normalize_update(update: Update) -> InboundMessage | None:
    """Return queryable inbound message fields for supported Telegram updates."""
    message = update.message
    if message is None or update.update_id is None:
        return None

    chat = update.effective_chat
    if chat is None:
        return None

    user = update.effective_user
    raw_update = update.to_dict() if hasattr(update, "to_dict") else None

    def inbound(
        *,
        message_type: str,
        text: str | None = None,
        file_id: str | None = None,
        file_unique_id: str | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
    ) -> InboundMessage:
        return InboundMessage(
            telegram_update_id=update.update_id,
            telegram_message_id=message.message_id,
            chat_id=chat.id,
            telegram_user_id=user.id if user else None,
            message_type=message_type,
            text=text,
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            received_at=message.date,
            raw_update=raw_update,
        )

    text = getattr(message, "text", None)
    if text and not text.startswith("/"):
        return inbound(message_type="text", text=text)

    for message_type, optional_fields in SUPPORTED_FILE_FIELDS.items():
        attachment = getattr(message, message_type, None)
        if not attachment:
            continue
        file = attachment[-1] if message_type == "photo" else attachment
        return inbound(
            message_type=message_type,
            file_id=file.file_id,
            file_unique_id=file.file_unique_id,
            file_name=getattr(file, "file_name", None)
            if "file_name" in optional_fields
            else None,
            mime_type=getattr(file, "mime_type", None)
            if "mime_type" in optional_fields
            else None,
            file_size=getattr(file, "file_size", None)
            if "file_size" in optional_fields
            else None,
        )

    return None


def persist_inbound_message(message: InboundMessage) -> dict[str, Any] | None:
    """Insert a normalized Telegram update once and return its durable row."""
    return _execute_returning(
        """
        INSERT INTO inbound_messages (
            telegram_update_id,
            telegram_message_id,
            chat_id,
            telegram_user_id,
            message_type,
            text,
            file_id,
            file_unique_id,
            file_name,
            mime_type,
            file_size,
            status,
            received_at,
            raw_update
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            'persisted',
            %s,
            %s
        )
        ON CONFLICT (telegram_update_id) DO UPDATE SET
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, status, retry_count
        """,
        (
            message.telegram_update_id,
            message.telegram_message_id,
            message.chat_id,
            message.telegram_user_id,
            message.message_type,
            message.text,
            message.file_id,
            message.file_unique_id,
            message.file_name,
            message.mime_type,
            message.file_size,
            message.received_at,
            Jsonb(message.raw_update) if message.raw_update is not None else None,
        ),
    )


def persist_update(update: Update) -> dict[str, Any] | None:
    """Normalize and persist a supported Telegram update."""
    message = normalize_update(update)
    if message is None:
        return None
    return persist_inbound_message(message)


def mark_queued(telegram_update_id: int) -> dict[str, Any] | None:
    """Move a persisted message into the processing queue when appropriate."""
    return _set_status(
        telegram_update_id,
        "queued",
        allowed_statuses=("persisted", "received", "failed"),
    )


def mark_processing(telegram_update_id: int) -> dict[str, Any] | None:
    """Claim a queued message for expensive processing."""
    return _execute_returning(
        """
        UPDATE inbound_messages
        SET status = 'processing',
            processing_started_at = CURRENT_TIMESTAMP,
            processing_finished_at = NULL,
            failed_at = NULL,
            failure_reason = NULL,
            retry_count = retry_count + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_update_id = %s
          AND status = 'queued'
        RETURNING id, status, retry_count
        """,
        (telegram_update_id,),
    )


def mark_answered(telegram_update_id: int) -> None:
    """Mark a message as answered after Telegram accepts the reply."""
    _execute(
        """
        UPDATE inbound_messages
        SET processing_finished_at = CURRENT_TIMESTAMP,
            answered_at = CURRENT_TIMESTAMP,
            failed_at = NULL,
            failure_reason = NULL,
            status = 'answered',
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_update_id = %s
          AND status = 'processing'
        """,
        (telegram_update_id,),
    )


def mark_failed(telegram_update_id: int, reason: str) -> None:
    """Mark a processing message as failed without logging private text."""
    _execute(
        """
        UPDATE inbound_messages
        SET processing_finished_at = CURRENT_TIMESTAMP,
            failed_at = CURRENT_TIMESTAMP,
            failure_reason = %s,
            status = 'failed',
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_update_id = %s
          AND status = ANY(%s)
        """,
        (reason[:500], telegram_update_id, ["processing", "queued", "persisted"]),
    )


def mark_ignored(telegram_update_id: int) -> None:
    """Mark a persisted supported message as intentionally not AI-processed."""
    _set_status(
        telegram_update_id,
        "ignored",
        allowed_statuses=("persisted", "received"),
    )


def recover_unfinished_messages() -> RecoverySummary:
    """Apply the startup recovery policy for unfinished inbound messages."""
    settings = get_settings()
    stale_before = datetime.now(timezone.utc) - timedelta(
        minutes=settings.message_processing_stale_minutes
    )
    expire_before = datetime.now(timezone.utc) - timedelta(
        hours=settings.message_expiration_hours
    )

    conn = conect_db()
    if not conn:
        return RecoverySummary(retried=0, expired=0, failed=0)

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE inbound_messages
                SET status = 'expired',
                    processing_finished_at = COALESCE(
                        processing_finished_at,
                        CURRENT_TIMESTAMP
                    ),
                    failed_at = COALESCE(failed_at, CURRENT_TIMESTAMP),
                    failure_reason = 'Expired before startup recovery',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('persisted', 'queued', 'processing', 'failed')
                  AND created_at < %s
                """,
                (expire_before,),
            )
            expired = int(cursor.rowcount or 0)

            cursor.execute(
                """
                UPDATE inbound_messages
                SET status = 'queued',
                    processing_started_at = NULL,
                    processing_finished_at = NULL,
                    failed_at = NULL,
                    failure_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'processing'
                  AND processing_started_at < %s
                  AND retry_count <= %s
                """,
                (stale_before, settings.message_max_retries),
            )
            retried = int(cursor.rowcount or 0)

            cursor.execute(
                """
                UPDATE inbound_messages
                SET status = 'failed',
                    processing_finished_at = COALESCE(
                        processing_finished_at,
                        CURRENT_TIMESTAMP
                    ),
                    failed_at = CURRENT_TIMESTAMP,
                    failure_reason = 'Retry limit reached during startup recovery',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'processing'
                  AND processing_started_at < %s
                  AND retry_count > %s
                """,
                (stale_before, settings.message_max_retries),
            )
            failed = int(cursor.rowcount or 0)

            conn.commit()
            return RecoverySummary(retried=retried, expired=expired, failed=failed)
    except psycopg.Error:
        conn.rollback()
        return RecoverySummary(retried=0, expired=0, failed=0)
    finally:
        conn.close()


def _set_status(
    telegram_update_id: int,
    status: str,
    *,
    allowed_statuses: tuple[str, ...],
) -> dict[str, Any] | None:
    return _execute_returning(
        """
        UPDATE inbound_messages
        SET status = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_update_id = %s
          AND status = ANY(%s)
        RETURNING id, status, retry_count
        """,
        (status, telegram_update_id, list(allowed_statuses)),
    )


def _execute(statement: str, params: tuple[Any, ...]) -> int:
    conn = conect_db()
    if not conn:
        return 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(statement, params)
            row_count = int(cursor.rowcount or 0)
            conn.commit()
            return row_count
    except psycopg.Error:
        conn.rollback()
        return 0
    finally:
        conn.close()


def _execute_returning(
    statement: str, params: tuple[Any, ...]
) -> dict[str, Any] | None:
    conn = conect_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(statement, params)
            row: dict[str, Any] | None = cursor.fetchone()
            conn.commit()
            return row
    except psycopg.Error:
        conn.rollback()
        return None
    finally:
        conn.close()
