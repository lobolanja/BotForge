from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from threading import RLock
from typing import Any, Protocol

import psycopg
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    messages_from_dict,
)
from langchain_postgres import PostgresChatMessageHistory
from psycopg import sql

from .bot_profile import SUPPORTED_MEMORY_BACKENDS, BotProfile, BotProfileError
from .config import get_settings
from .database import conect_db
from .memory_store import (
    ConversationMemoryStore,
    MemoryContext,
    MemorySummarizer,
    memory_store,
)
from .prompting import ChatMessage

logger = logging.getLogger(__name__)

LANGCHAIN_CHAT_HISTORY_TABLE = "langchain_chat_history"
LANGCHAIN_CHAT_SESSIONS_TABLE = "langchain_chat_sessions"
LANGCHAIN_COMPACTION_VERSION = "langchain-postgres-chat-history-v1"
LANGCHAIN_SESSION_NAMESPACE = uuid.UUID("6a049dbd-6906-4e05-a803-a2d19953e3cc")


class MemoryBackend(Protocol):
    """Prompt-facing memory interface used by Telegram routing."""

    def get_context(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        exclude_inbound_message_id: int | None = None,
    ) -> MemoryContext:
        """Return memory context for the current turn."""

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
        """Persist one successful user/assistant turn."""

    async def compact_memory_if_needed(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        summarizer: MemorySummarizer,
    ) -> None:
        """Compact old memory when the backend supports compaction."""


class PostgresMemoryBackend:
    """Existing BotForge PostgreSQL memory backend."""

    def __init__(self, store: ConversationMemoryStore = memory_store) -> None:
        self._store = store

    def get_context(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        exclude_inbound_message_id: int | None = None,
    ) -> MemoryContext:
        return self._store.get_context(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            exclude_inbound_message_id=exclude_inbound_message_id,
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
        return self._store.store_successful_turn(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            user_message=user_message,
            assistant_message=assistant_message,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            inbound_message_id=inbound_message_id,
            request_id=request_id,
        )

    async def compact_memory_if_needed(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        summarizer: MemorySummarizer,
    ) -> None:
        await self._store.compact_memory_if_needed(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            summarizer=summarizer,
        )


class LangChainPostgresMemoryBackend(PostgresMemoryBackend):
    """Memory backend using LangChain's maintained PostgreSQL chat history."""

    _compaction_locks: dict[tuple[int, str], asyncio.Lock] = {}
    _lock = RLock()

    def get_context(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        exclude_inbound_message_id: int | None = None,
    ) -> MemoryContext:
        del exclude_inbound_message_id

        if not self._ensure_session_mapping(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
        ):
            return MemoryContext(
                compacted_user_memory=None,
                recent_conversation_messages=[],
            )

        summary, _source_message_count = self._read_summary_state(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
        )
        settings = get_settings()
        messages = self._get_recent_langchain_messages(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            limit=settings.memory_recent_messages,
        )
        return MemoryContext(
            compacted_user_memory=summary,
            recent_conversation_messages=[
                _from_langchain_message(message) for message in messages
            ],
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
        del telegram_chat_id, telegram_message_id, inbound_message_id, request_id

        if not self._ensure_session_mapping(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
        ):
            return False

        settings = get_settings()
        try:
            self._add_langchain_messages(
                user_id=user_id,
                bot_profile_id=bot_profile_id,
                messages=[
                    HumanMessage(
                        content=_truncate(
                            user_message,
                            settings.memory_max_message_chars,
                        )
                    ),
                    AIMessage(
                        content=_truncate(
                            assistant_message,
                            settings.memory_max_message_chars,
                        )
                    ),
                ],
            )
            return True
        except Exception:
            logger.exception(
                "langchain_memory_turn_insert_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
            return False

    async def compact_memory_if_needed(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        summarizer: MemorySummarizer,
    ) -> None:
        compaction_lock = self._get_compaction_lock(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
        )
        async with compaction_lock:
            existing_summary, source_message_count = self._read_summary_state(
                user_id=user_id,
                bot_profile_id=bot_profile_id,
            )
            settings = get_settings()
            unsummarized = [
                _from_langchain_message(message)
                for message in self._get_unsummarized_langchain_messages(
                    user_id=user_id,
                    bot_profile_id=bot_profile_id,
                    source_message_count=source_message_count,
                    limit=settings.memory_compaction_trigger_messages,
                )
            ]
            if len(unsummarized) < settings.memory_compaction_trigger_messages:
                return

            source = unsummarized[: settings.memory_compaction_source_messages]
            summary = await summarizer(
                existing_summary,
                source,
                settings.memory_compacted_max_chars,
            )
            if not summary or not summary.strip():
                return

            clean_summary = _truncate(
                summary.strip(),
                settings.memory_compacted_max_chars,
            )
            self._save_summary_state(
                user_id=user_id,
                bot_profile_id=bot_profile_id,
                summary=clean_summary,
                source_message_count=source_message_count + len(source),
            )

    @classmethod
    def _get_compaction_lock(
        cls,
        *,
        user_id: int,
        bot_profile_id: str,
    ) -> asyncio.Lock:
        key = (user_id, bot_profile_id)
        with cls._lock:
            lock = cls._compaction_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                cls._compaction_locks[key] = lock
            return lock

    def _get_langchain_messages(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
    ) -> list[BaseMessage]:
        try:
            with self._history_for(
                user_id=user_id,
                bot_profile_id=bot_profile_id,
            ) as history:
                if history is None:
                    return []
                return list(history.messages)
        except Exception:
            logger.exception(
                "langchain_memory_context_load_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
            return []

    def _get_recent_langchain_messages(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        limit: int,
    ) -> list[BaseMessage]:
        if limit <= 0:
            return []
        rows = self._fetch_langchain_message_payloads(
            session_id=_session_id(user_id=user_id, bot_profile_id=bot_profile_id),
            order_desc=True,
            limit=limit,
        )
        rows.reverse()
        return _messages_from_payloads(rows)

    def _get_unsummarized_langchain_messages(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        source_message_count: int,
        limit: int,
    ) -> list[BaseMessage]:
        if limit <= 0:
            return []
        rows = self._fetch_langchain_message_payloads(
            session_id=_session_id(user_id=user_id, bot_profile_id=bot_profile_id),
            order_desc=False,
            limit=limit,
            offset=max(source_message_count, 0),
        )
        return _messages_from_payloads(rows)

    def _fetch_langchain_message_payloads(
        self,
        *,
        session_id: str,
        order_desc: bool,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conn = conect_db()
        if not conn:
            return []

        order = "DESC" if order_desc else "ASC"
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("""
                    SELECT message
                    FROM {}
                    WHERE session_id = %s
                    ORDER BY id {}
                    LIMIT %s
                    OFFSET %s
                    """).format(
                        sql.Identifier(LANGCHAIN_CHAT_HISTORY_TABLE),
                        sql.SQL(order),
                    ),
                    (session_id, limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error:
            logger.exception(
                "langchain_memory_window_load_failed session_id=%s", session_id
            )
            return []
        finally:
            conn.close()

        payloads: list[dict[str, Any]] = []
        for row in rows:
            message = row.get("message")
            if isinstance(message, dict):
                payloads.append(message)
        return payloads

    def _add_langchain_messages(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        messages: Sequence[BaseMessage],
    ) -> None:
        with self._history_for(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
        ) as history:
            if history is None:
                raise RuntimeError("LangChain PostgreSQL history is unavailable.")
            history.add_messages(messages)

    @contextmanager
    def _history_for(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
    ) -> Iterator[PostgresChatMessageHistory | None]:
        conn = _connect_langchain_history_db()
        if conn is None:
            yield None
            return
        try:
            yield PostgresChatMessageHistory(
                LANGCHAIN_CHAT_HISTORY_TABLE,
                _session_id(user_id=user_id, bot_profile_id=bot_profile_id),
                sync_connection=conn,
            )
        finally:
            conn.close()

    def _ensure_session_mapping(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
    ) -> bool:
        conn = conect_db()
        if not conn:
            return False

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("""
                    INSERT INTO {} (
                        user_id,
                        bot_profile_id,
                        session_id
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, bot_profile_id)
                    DO UPDATE SET
                        session_id = EXCLUDED.session_id,
                        updated_at = CURRENT_TIMESTAMP
                    """).format(sql.Identifier(LANGCHAIN_CHAT_SESSIONS_TABLE)),
                    (
                        user_id,
                        bot_profile_id,
                        _session_id(user_id=user_id, bot_profile_id=bot_profile_id),
                    ),
                )
                conn.commit()
            return True
        except psycopg.Error:
            conn.rollback()
            logger.exception(
                "langchain_memory_session_mapping_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
            return False
        finally:
            conn.close()

    def _read_summary_state(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
    ) -> tuple[str | None, int]:
        conn = conect_db()
        if not conn:
            return None, 0

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT summary, source_message_count
                    FROM user_memory_summaries
                    WHERE user_id = %s
                      AND bot_profile_id = %s
                      AND deleted_at IS NULL
                    """,
                    (user_id, bot_profile_id),
                )
                row = cursor.fetchone()
        except psycopg.Error:
            logger.exception(
                "langchain_memory_summary_load_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
            return None, 0
        finally:
            conn.close()

        if not row:
            return None, 0
        return str(row["summary"]), int(row["source_message_count"] or 0)

    def _save_summary_state(
        self,
        *,
        user_id: int,
        bot_profile_id: str,
        summary: str,
        source_message_count: int,
    ) -> None:
        conn = conect_db()
        if not conn:
            return

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
                        source_message_count = EXCLUDED.source_message_count,
                        compaction_version = EXCLUDED.compaction_version,
                        updated_at = CURRENT_TIMESTAMP,
                        deleted_at = NULL
                    """,
                    (
                        user_id,
                        bot_profile_id,
                        summary,
                        source_message_count,
                        LANGCHAIN_COMPACTION_VERSION,
                    ),
                )
                conn.commit()
        except psycopg.Error:
            conn.rollback()
            logger.exception(
                "langchain_memory_summary_save_failed user_id=%s bot_profile_id=%s",
                user_id,
                bot_profile_id,
            )
        finally:
            conn.close()


def memory_backend_for_profile(profile: BotProfile) -> MemoryBackend:
    """Return the configured memory backend for one bot profile."""
    backend_name = profile.memory_backend.strip().lower()
    if backend_name == "postgres":
        return PostgresMemoryBackend()
    if backend_name == "langchain_postgres":
        return LangChainPostgresMemoryBackend()

    options = ", ".join(sorted(SUPPORTED_MEMORY_BACKENDS))
    raise BotProfileError(
        f"Unsupported memory backend '{profile.memory_backend}' for profile "
        f"'{profile.bot_profile_id}'. Expected one of: {options}."
    )


def _from_langchain_message(message: BaseMessage) -> ChatMessage:
    role = "assistant" if isinstance(message, AIMessage) else "user"
    content = message.content
    if isinstance(content, str):
        text = content
    else:
        text = "\n".join(str(item) for item in content)
    return {"role": role, "content": text}


def _messages_from_payloads(payloads: Sequence[dict[str, Any]]) -> list[BaseMessage]:
    try:
        return list(messages_from_dict(list(payloads)))
    except Exception:
        logger.exception("langchain_memory_message_decode_failed")
        return []


def _session_id(*, user_id: int, bot_profile_id: str) -> str:
    return str(
        uuid.uuid5(
            LANGCHAIN_SESSION_NAMESPACE,
            f"{user_id}:{bot_profile_id}",
        )
    )


def _connect_langchain_history_db() -> psycopg.Connection[tuple[Any, ...]] | None:
    settings = get_settings()
    try:
        return psycopg.connect(
            host=settings.db_host,
            user=settings.db_user,
            password=settings.db_password,
            dbname=settings.db_name,
            port=settings.db_port,
        )
    except psycopg.Error:
        logger.exception("langchain_memory_database_connection_failed")
        return None


def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip()
