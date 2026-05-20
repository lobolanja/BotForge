from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Any

import psycopg

from .config import get_settings
from .database import conect_db
from .prompting import ChatMessage

logger = logging.getLogger(__name__)

ALLOWED_ROLES = frozenset({"user", "assistant"})
COMPACTION_VERSION = "botforge-memory-v1"
MemorySummarizer = Callable[
    [str | None, Sequence[ChatMessage], int],
    Awaitable[str | None],
]


@dataclass(frozen=True)
class ConversationMessage:
    id: int | None
    role: str
    content: str
    created_at: datetime | None = None
    summarized_at: datetime | None = None

    def as_chat_message(self) -> ChatMessage:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class MemoryContext:
    compacted_user_memory: str | None
    recent_conversation_messages: list[ChatMessage]


@dataclass
class _CachedMemory:
    compacted_user_memory: str | None
    recent_messages: list[ConversationMessage]


class ConversationMemoryStore:
    """PostgreSQL-backed memory with a small process-local prompt cache."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, str], _CachedMemory] = {}
        self._lock = RLock()

    def get_context(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        exclude_inbound_message_id: int | None = None,
    ) -> MemoryContext:
        cached = self._get_or_load(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            exclude_inbound_message_id=exclude_inbound_message_id,
        )
        return MemoryContext(
            compacted_user_memory=cached.compacted_user_memory,
            recent_conversation_messages=[
                message.as_chat_message() for message in cached.recent_messages
            ],
        )

    async def add_successful_turn(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        user_message: str,
        assistant_message: str,
        telegram_chat_id: int | None = None,
        telegram_message_id: int | None = None,
        inbound_message_id: int | None = None,
        request_id: str | None = None,
        summarizer: MemorySummarizer | None = None,
    ) -> None:
        stored = self.store_successful_turn(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            user_message=user_message,
            assistant_message=assistant_message,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            inbound_message_id=inbound_message_id,
            request_id=request_id,
        )
        if not stored:
            return

        if summarizer is not None:
            await self.compact_memory_if_needed(
                user_id=user_id,
                bot_profile_id=bot_profile_id,
                summarizer=summarizer,
            )

    def store_successful_turn(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        user_message: str,
        assistant_message: str,
        telegram_chat_id: int | None = None,
        telegram_message_id: int | None = None,
        inbound_message_id: int | None = None,
        request_id: str | None = None,
    ) -> bool:
        cached = self._get_or_load(user_id=user_id, bot_profile_id=bot_profile_id)
        new_messages = self._insert_turn(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            user_message=user_message,
            assistant_message=assistant_message,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            inbound_message_id=inbound_message_id,
            request_id=request_id,
        )
        if not new_messages:
            return False

        settings = get_settings()
        with self._lock:
            cached.recent_messages.extend(new_messages)
            cached.recent_messages = cached.recent_messages[
                -settings.memory_recent_messages :
            ]
        return True

    async def compact_memory_if_needed(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        summarizer: MemorySummarizer,
    ) -> None:
        cached = self._get_or_load(user_id=user_id, bot_profile_id=bot_profile_id)
        await self._compact_if_needed(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            cached=cached,
            summarizer=summarizer,
        )

    def clear_cached_user(
        self,
        *,
        user_id: int,
        bot_profile_id: str | None = None,
    ) -> None:
        with self._lock:
            if bot_profile_id is None:
                keys = [key for key in self._cache if key[0] == user_id]
                for key in keys:
                    del self._cache[key]
                return
            self._cache.pop((user_id, bot_profile_id), None)

    async def _compact_if_needed(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        cached: _CachedMemory,
        summarizer: MemorySummarizer,
    ) -> None:
        settings = get_settings()
        with self._lock:
            unsummarized = [
                message
                for message in cached.recent_messages
                if message.id is not None and message.summarized_at is None
            ]
            if len(unsummarized) < settings.memory_compaction_trigger_messages:
                return
            source = unsummarized[: settings.memory_compaction_source_messages]

        source_chat_messages = [message.as_chat_message() for message in source]
        summary = await summarizer(
            cached.compacted_user_memory,
            source_chat_messages,
            settings.memory_compacted_max_chars,
        )
        if not summary or not summary.strip():
            return

        clean_summary = _truncate(summary.strip(), settings.memory_compacted_max_chars)
        source_ids = [int(message.id) for message in source if message.id is not None]
        if not self._save_summary_and_mark_sources(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            summary=clean_summary,
            source_ids=source_ids,
        ):
            return

        with self._lock:
            cached.compacted_user_memory = clean_summary
            summarized_ids = set(source_ids)
            cached.recent_messages = [
                (
                    ConversationMessage(
                        id=message.id,
                        role=message.role,
                        content=message.content,
                        created_at=message.created_at,
                        summarized_at=datetime.now(),
                    )
                    if message.id in summarized_ids
                    else message
                )
                for message in cached.recent_messages
            ]

    def _get_or_load(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        exclude_inbound_message_id: int | None = None,
    ) -> _CachedMemory:
        key = (user_id, bot_profile_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        loaded = self._load_from_database(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            exclude_inbound_message_id=exclude_inbound_message_id,
        )
        with self._lock:
            return self._cache.setdefault(key, loaded)

    def _load_from_database(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        exclude_inbound_message_id: int | None = None,
    ) -> _CachedMemory:
        settings = get_settings()
        conn = conect_db()
        if not conn:
            return _CachedMemory(compacted_user_memory=None, recent_messages=[])

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT summary
                    FROM user_memory_summaries
                    WHERE user_id = %s
                      AND bot_profile_id = %s
                      AND deleted_at IS NULL
                    """,
                    (user_id, bot_profile_id),
                )
                summary_row = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT id, role, content, created_at, summarized_at
                    FROM conversation_messages
                    WHERE user_id = %s
                      AND bot_profile_id = %s
                      AND deleted_at IS NULL
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (user_id, bot_profile_id, settings.memory_recent_messages),
                )
                rows = list(cursor.fetchall())
        except psycopg.Error:
            logger.exception(
                "memory_context_load_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
            return _CachedMemory(compacted_user_memory=None, recent_messages=[])
        finally:
            conn.close()

        messages = [
            ConversationMessage(
                id=int(row["id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=row["created_at"],
                summarized_at=row["summarized_at"],
            )
            for row in reversed(rows)
        ]
        if not messages:
            messages = self._load_recent_inbound_messages(
                user_id=user_id,
                limit=settings.memory_recent_messages,
                exclude_inbound_message_id=exclude_inbound_message_id,
            )
        summary = str(summary_row["summary"]) if summary_row else None
        return _CachedMemory(compacted_user_memory=summary, recent_messages=messages)

    def _load_recent_inbound_messages(
        self,
        *,
        user_id: int,
        limit: int,
        exclude_inbound_message_id: int | None,
    ) -> list[ConversationMessage]:
        conn = conect_db()
        if not conn:
            return []

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT im.id, im.text, im.created_at
                    FROM inbound_messages im
                    JOIN users u ON u.telegram_id = im.telegram_user_id
                    WHERE u.id = %s
                      AND u.deleted_at IS NULL
                      AND im.message_type = 'text'
                      AND im.text IS NOT NULL
                      AND im.status = 'answered'
                      AND (%s IS NULL OR im.id <> %s)
                    ORDER BY im.created_at DESC, im.id DESC
                    LIMIT %s
                    """,
                    (
                        user_id,
                        exclude_inbound_message_id,
                        exclude_inbound_message_id,
                        limit,
                    ),
                )
                rows = list(cursor.fetchall())
        except psycopg.Error:
            logger.exception("memory_inbound_bootstrap_failed user_id=%s", user_id)
            return []
        finally:
            conn.close()

        return [
            ConversationMessage(
                id=None,
                role="user",
                content=str(row["text"]),
                created_at=row["created_at"],
            )
            for row in reversed(rows)
        ]

    def _insert_turn(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        user_message: str,
        assistant_message: str,
        telegram_chat_id: int | None,
        telegram_message_id: int | None,
        inbound_message_id: int | None,
        request_id: str | None,
    ) -> list[ConversationMessage]:
        settings = get_settings()
        user_content = _truncate(user_message, settings.memory_max_message_chars)
        assistant_content = _truncate(
            assistant_message,
            settings.memory_max_message_chars,
        )
        conn = conect_db()
        if not conn:
            return []

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_messages (
                        user_id,
                        bot_profile_id,
                        telegram_chat_id,
                        telegram_message_id,
                        inbound_message_id,
                        request_id,
                        role,
                        content,
                        content_chars
                    )
                    VALUES
                        (%s, %s, %s, %s, %s, %s, 'user', %s, %s),
                        (%s, %s, %s, NULL, NULL, %s, 'assistant', %s, %s)
                    RETURNING id, role, content, created_at, summarized_at
                    """,
                    (
                        user_id,
                        bot_profile_id,
                        telegram_chat_id,
                        telegram_message_id,
                        inbound_message_id,
                        request_id,
                        user_content,
                        len(user_content),
                        user_id,
                        bot_profile_id,
                        telegram_chat_id,
                        request_id,
                        assistant_content,
                        len(assistant_content),
                    ),
                )
                rows = list(cursor.fetchall())
                self._prune_recent_messages(
                    cursor,
                    user_id=user_id,
                    bot_profile_id=bot_profile_id,
                    limit=settings.memory_recent_messages,
                )
                conn.commit()
        except psycopg.Error:
            conn.rollback()
            logger.exception(
                "memory_turn_insert_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
            return []
        finally:
            conn.close()

        return [
            ConversationMessage(
                id=int(row["id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=row["created_at"],
                summarized_at=row["summarized_at"],
            )
            for row in rows
        ]

    def _prune_recent_messages(
        self,
        cursor: Any,
        *,
        user_id: int,
        bot_profile_id: str,
        limit: int,
    ) -> None:
        cursor.execute(
            """
            DELETE FROM conversation_messages
            WHERE user_id = %s
              AND bot_profile_id = %s
              AND id NOT IN (
                  SELECT id
                  FROM conversation_messages
                  WHERE user_id = %s
                    AND bot_profile_id = %s
                    AND deleted_at IS NULL
                  ORDER BY created_at DESC, id DESC
                  LIMIT %s
              )
            """,
            (user_id, bot_profile_id, user_id, bot_profile_id, limit),
        )

    def _save_summary_and_mark_sources(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        summary: str,
        source_ids: Sequence[int],
    ) -> bool:
        if not source_ids:
            return False
        conn = conect_db()
        if not conn:
            return False

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_memory_summaries (
                        user_id,
                        bot_profile_id,
                        summary,
                        source_message_count,
                        compaction_version
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, bot_profile_id)
                    DO UPDATE SET
                        summary = EXCLUDED.summary,
                        source_message_count =
                            user_memory_summaries.source_message_count
                            + EXCLUDED.source_message_count,
                        compaction_version = EXCLUDED.compaction_version,
                        updated_at = CURRENT_TIMESTAMP,
                        deleted_at = NULL
                    """,
                    (
                        user_id,
                        bot_profile_id,
                        summary,
                        len(source_ids),
                        COMPACTION_VERSION,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE conversation_messages
                    SET summarized_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s
                      AND bot_profile_id = %s
                      AND id = ANY(%s)
                      AND summarized_at IS NULL
                      AND deleted_at IS NULL
                    """,
                    (user_id, bot_profile_id, list(source_ids)),
                )
                conn.commit()
                return True
        except psycopg.Error:
            conn.rollback()
            logger.exception(
                "memory_summary_save_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
            return False
        finally:
            conn.close()


def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip()


memory_store = ConversationMemoryStore()


def get_memory_context(
    *,
    user_id: int,
    bot_profile_id: str,
    exclude_inbound_message_id: int | None = None,
) -> MemoryContext:
    return memory_store.get_context(
        user_id=user_id,
        bot_profile_id=bot_profile_id,
        exclude_inbound_message_id=exclude_inbound_message_id,
    )


def store_successful_turn(
    *,
    user_id: int,
    bot_profile_id: str,
    user_message: str,
    assistant_message: str,
    telegram_chat_id: int | None = None,
    telegram_message_id: int | None = None,
    inbound_message_id: int | None = None,
    request_id: str | None = None,
) -> bool:
    return memory_store.store_successful_turn(
        user_id=user_id,
        bot_profile_id=bot_profile_id,
        user_message=user_message,
        assistant_message=assistant_message,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        inbound_message_id=inbound_message_id,
        request_id=request_id,
    )


async def add_successful_turn(
    *,
    user_id: int,
    bot_profile_id: str,
    user_message: str,
    assistant_message: str,
    telegram_chat_id: int | None = None,
    telegram_message_id: int | None = None,
    inbound_message_id: int | None = None,
    request_id: str | None = None,
    summarizer: MemorySummarizer | None = None,
) -> None:
    await memory_store.add_successful_turn(
        user_id=user_id,
        bot_profile_id=bot_profile_id,
        user_message=user_message,
        assistant_message=assistant_message,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        inbound_message_id=inbound_message_id,
        request_id=request_id,
        summarizer=summarizer,
    )


async def compact_memory_if_needed(
    *,
    user_id: int,
    bot_profile_id: str,
    summarizer: MemorySummarizer,
) -> None:
    await memory_store.compact_memory_if_needed(
        user_id=user_id,
        bot_profile_id=bot_profile_id,
        summarizer=summarizer,
    )


def clear_cached_user_memory(
    *,
    user_id: int,
    bot_profile_id: str | None = None,
) -> None:
    memory_store.clear_cached_user(user_id=user_id, bot_profile_id=bot_profile_id)
