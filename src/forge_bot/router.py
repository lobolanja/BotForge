import asyncio
import contextlib
import logging
import time
from collections.abc import Sequence

from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from . import engine
from .bot_profile import BotProfile
from .commands.auth_guard import require_login
from .config import get_settings
from .database import get_user_by_telegram_id
from .debug_conversation_log import (
    DebugConversationTurn,
    append_debug_conversation_turn,
)
from .memory_backend import MemoryBackend, memory_backend_for_profile
from .message_store import (
    mark_answered,
    mark_failed,
    mark_ignored,
    mark_processing,
    mark_queued,
    normalize_update,
    persist_inbound_message,
    persist_update,
)
from .prompting import ChatMessage
from .rate_limits import LimitDecision, abuse_limiter
from .request_state import REQUEST_WAITING_MESSAGE, request_state

logger = logging.getLogger(__name__)
PROCESSING_NOTICE_INITIAL_DELAY_SECONDS = 15
PROCESSING_NOTICE_INTERVAL_SECONDS = 60
PROCESSING_NOTICE_MESSAGE = (
    "Estoy revisandolo. Puede tardar un poco; no hace falta que lo reenvies."
)
PROCESSING_NOTICE_REPEAT_MESSAGE = (
    "Sigo trabajando en tu respuesta. Te contesto aqui en cuanto termine."
)
STREAM_LOADING_DRAFT_INTERVAL_SECONDS = 2.0
STREAM_DRAFT_UPDATE_INTERVAL_SECONDS = 2.0


async def record_inbound_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Persist supported Telegram updates before later handler groups run."""
    del context

    inbound_message = normalize_update(update)
    if inbound_message is None:
        return

    row = persist_inbound_message(inbound_message)
    if row and inbound_message.message_type != "text":
        mark_ignored(inbound_message.telegram_update_id)


@require_login
async def ask_ia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route identity-linked plain-text Telegram messages to the AI engine."""
    if (
        not update.message
        or not update.effective_user
        or not update.effective_chat
        or update.update_id is None
    ):
        return

    persisted = persist_update(update)
    if persisted is None:
        await update.message.reply_text(
            "Message storage is temporarily unavailable. Please try again in a moment."
        )
        return

    current_status = persisted["status"]
    if current_status in {"answered", "ignored", "expired"}:
        return
    if current_status == "processing":
        return

    message = update.message.text or ""
    limit_decision = _first_rejected_limit(update, message)
    if limit_decision:
        await _ignore_with_reply(update, limit_decision.message)
        return

    active_profile = engine.load_default_profile()
    memory_is_enabled = _memory_enabled(active_profile)
    memory_backend = memory_backend_for_profile(active_profile)
    needs_internal_user = (
        memory_is_enabled or active_profile.bot_profile_id == "nutrition"
    )
    internal_user = (
        get_user_by_telegram_id(update.effective_user.id)
        if needs_internal_user
        else None
    )
    memory_context = None
    if internal_user and memory_is_enabled:
        memory_context = memory_backend.get_context(
            user_id=int(internal_user["id"]),
            bot_profile_id=active_profile.bot_profile_id,
            exclude_inbound_message_id=(
                int(persisted["id"]) if persisted.get("id") is not None else None
            ),
        )
        logger.info(
            "memory_context_loaded request_update_id=%s user_id=%s "
            "bot_profile_id=%s recent_messages=%s compacted_chars=%s",
            update.update_id,
            int(internal_user["id"]),
            active_profile.bot_profile_id,
            len(memory_context.recent_conversation_messages),
            len(memory_context.compacted_user_memory or ""),
        )

    active_request = await request_state.try_start(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        received_at=update.message.date,
        provider=active_profile.llm_provider,
    )
    if active_request is None:
        await _ignore_with_reply(update, REQUEST_WAITING_MESSAGE)
        return

    ai_lease = await abuse_limiter.acquire_ai_request(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
    )
    if isinstance(ai_lease, LimitDecision):
        await _finish_ignored_request(
            update, active_request.request_id, ai_lease.message
        )
        return

    ai_decision = abuse_limiter.check_user_ai_request(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
    )
    if not ai_decision.allowed:
        await ai_lease.release()
        await _finish_ignored_request(
            update, active_request.request_id, ai_decision.message
        )
        return

    processing_request = await request_state.mark_processing_started(
        user_id=update.effective_user.id,
        request_id=active_request.request_id,
    )
    if processing_request is None:
        await ai_lease.release()
        return

    finished_status = "failed"
    memory_compaction_job: tuple[int, str, str, BotProfile, MemoryBackend] | None = None
    processing_notice_task: asyncio.Task[None] | None = None
    stream_loading_task: asyncio.Task[None] | None = None

    try:
        if current_status in {"persisted", "received", "failed"}:
            mark_queued(update.update_id)

        claimed = mark_processing(update.update_id)
        if claimed is None:
            return

        # Extract the visible user name.
        user = update.effective_user.first_name

        # Show Telegram's typing indicator while the LLM response is generated.
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
        draft_streamer = _TelegramDraftStreamer(
            context.bot,
            chat_id=update.effective_chat.id,
            draft_id=update.update_id,
        )
        streaming_enabled = _streaming_enabled(active_profile)
        if streaming_enabled:
            stream_loading_task = asyncio.create_task(
                _send_loading_drafts(draft_streamer)
            )
        else:
            processing_notice_task = asyncio.create_task(
                _send_processing_notices(update.message)
            )

        async def publish_partial_answer(text: str) -> None:
            nonlocal processing_notice_task
            nonlocal stream_loading_task
            if stream_loading_task is not None:
                stream_loading_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_loading_task
                stream_loading_task = None
            if processing_notice_task is not None:
                processing_notice_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await processing_notice_task
                processing_notice_task = None
            await draft_streamer.publish(text, force=True)

        compacted_user_memory = (
            memory_context.compacted_user_memory if memory_context else None
        )
        recent_conversation_messages = (
            memory_context.recent_conversation_messages if memory_context else []
        )
        internal_user_id = (
            int(internal_user["id"])
            if internal_user and internal_user.get("id") is not None
            else None
        )
        # Delegate prompt assembly and LLM provider selection to the engine module.
        if streaming_enabled:
            answer = await engine.answer_stream(
                user,
                message,
                on_partial=publish_partial_answer,
                profile=active_profile,
                request_id=processing_request.request_id,
                queue_wait_seconds=processing_request.queue_wait_seconds,
                compacted_user_memory=compacted_user_memory,
                recent_conversation_messages=recent_conversation_messages,
                internal_user_id=internal_user_id,
            )
        else:
            answer = await engine.answer(
                user,
                message,
                profile=active_profile,
                request_id=processing_request.request_id,
                queue_wait_seconds=processing_request.queue_wait_seconds,
                compacted_user_memory=compacted_user_memory,
                recent_conversation_messages=recent_conversation_messages,
                internal_user_id=internal_user_id,
            )

        # Send the generated answer back into the same chat.
        await _reply_ai_answer(update.message, answer)
        mark_answered(update.update_id)
        engine.finalize_successful_answer(answer)
        if engine.answer_should_be_debug_logged(answer):
            _append_debug_conversation_turn(
                profile=active_profile,
                user_message=message,
                assistant_message=answer,
                telegram_user_id=update.effective_user.id,
                telegram_chat_id=update.effective_chat.id,
                telegram_message_id=getattr(update.message, "message_id", None),
                inbound_message_id=claimed.get("id") if claimed else None,
                request_id=processing_request.request_id,
                internal_user_id=(
                    int(internal_user["id"])
                    if internal_user and internal_user.get("id") is not None
                    else None
                ),
            )
        if (
            internal_user
            and memory_is_enabled
            and engine.answer_should_be_stored_in_memory(answer)
        ):
            stored = _store_successful_turn(
                internal_user_id=int(internal_user["id"]),
                bot_profile_id=active_profile.bot_profile_id,
                user_message=message,
                assistant_message=answer,
                telegram_chat_id=update.effective_chat.id,
                telegram_message_id=getattr(update.message, "message_id", None),
                inbound_message_id=claimed.get("id") if claimed else None,
                request_id=processing_request.request_id,
                memory_backend=memory_backend,
            )
            if stored:
                memory_compaction_job = (
                    int(internal_user["id"]),
                    active_profile.bot_profile_id,
                    processing_request.request_id,
                    active_profile,
                    memory_backend,
                )
        finished_status = "answered"
    except Exception as exc:
        mark_failed(update.update_id, type(exc).__name__)
        await update.message.reply_text(
            "I could not finish that message right now. It has been stored for "
            "review. Please try again in a moment."
        )
    finally:
        if stream_loading_task is not None:
            stream_loading_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stream_loading_task
        if processing_notice_task is not None:
            processing_notice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await processing_notice_task
        await ai_lease.release()
        await request_state.finish(
            user_id=update.effective_user.id,
            request_id=active_request.request_id,
            status=finished_status,
        )
    if memory_compaction_job is not None:
        await _compact_successful_turn(
            internal_user_id=memory_compaction_job[0],
            bot_profile_id=memory_compaction_job[1],
            request_id=memory_compaction_job[2],
            profile=memory_compaction_job[3],
            memory_backend=memory_compaction_job[4],
        )


def _memory_enabled(profile: BotProfile) -> bool:
    if not profile.memory_enabled:
        return False
    return get_settings().memory_enabled


def _streaming_enabled(profile: BotProfile) -> bool:
    settings = get_settings()
    configured_primary_provider = settings.llm_primary_provider.lower()
    profile_provider = profile.llm_provider.lower()
    return configured_primary_provider == "nvidia" or (
        configured_primary_provider in {"", "profile"} and profile_provider == "nvidia"
    )


def _store_successful_turn(
    *,
    internal_user_id: int,
    bot_profile_id: str,
    user_message: str,
    assistant_message: str,
    telegram_chat_id: int | None,
    telegram_message_id: int | None,
    inbound_message_id: int | None,
    request_id: str,
    memory_backend: MemoryBackend,
) -> bool:
    try:
        return memory_backend.store_successful_turn(
            user_id=internal_user_id,
            bot_profile_id=bot_profile_id,
            user_message=user_message,
            assistant_message=assistant_message,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            inbound_message_id=inbound_message_id,
            request_id=request_id,
        )
    except Exception:
        # The user already received the answer. Memory must not turn that into
        # a failed inbound message or leak raw content into logs.
        logger.exception(
            "memory_store_after_answer_failed request_id=%s user_id=%s",
            request_id,
            internal_user_id,
        )
        return False


def _append_debug_conversation_turn(
    *,
    profile: BotProfile,
    user_message: str,
    assistant_message: str,
    telegram_user_id: int,
    telegram_chat_id: int,
    telegram_message_id: int | None,
    inbound_message_id: int | None,
    request_id: str,
    internal_user_id: int | None,
) -> None:
    append_debug_conversation_turn(
        DebugConversationTurn(
            bot_profile_id=profile.bot_profile_id,
            internal_user_id=internal_user_id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            inbound_message_id=inbound_message_id,
            request_id=request_id,
            user_message=user_message,
            assistant_message=assistant_message,
        )
    )


async def _compact_successful_turn(
    *,
    internal_user_id: int,
    bot_profile_id: str,
    request_id: str,
    profile: BotProfile,
    memory_backend: MemoryBackend,
) -> None:
    async def summarize(
        existing_summary: str | None,
        source_messages: Sequence[ChatMessage],
        max_chars: int,
    ) -> str | None:
        return await engine.summarize_memory(
            profile=profile,
            existing_summary=existing_summary,
            source_messages=source_messages,
            max_chars=max_chars,
            request_id=request_id,
        )

    try:
        await memory_backend.compact_memory_if_needed(
            user_id=internal_user_id,
            bot_profile_id=bot_profile_id,
            summarizer=summarize,
        )
    except Exception:
        logger.exception(
            "memory_compaction_after_answer_failed request_id=%s user_id=%s",
            request_id,
            internal_user_id,
        )


def _first_rejected_limit(update: Update, message: str) -> LimitDecision | None:
    if not update.effective_user or not update.effective_chat:
        return None

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    decision = abuse_limiter.check_message_length(
        user_id=user_id,
        chat_id=chat_id,
        text=message,
    )
    if decision.allowed:
        decision = abuse_limiter.check_message_rate(user_id=user_id, chat_id=chat_id)
    return None if decision.allowed else decision


async def _ignore_with_reply(update: Update, message: str) -> None:
    if update.update_id is not None:
        mark_ignored(update.update_id)
    if update.message:
        await update.message.reply_text(message)


async def _reply_ai_answer(message: object, answer: str) -> None:
    try:
        await message.reply_text(answer, parse_mode="HTML")  # type: ignore[attr-defined]
    except TypeError:
        await message.reply_text(answer)  # type: ignore[attr-defined]


class _TelegramDraftStreamer:
    def __init__(self, bot: object, *, chat_id: int, draft_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._draft_id = draft_id
        self._last_text = ""
        self._last_sent_at = 0.0
        self._retry_after_until = 0.0
        self._disabled = False

    async def publish(
        self,
        text: str,
        *,
        force: bool = False,
        min_interval_seconds: float = STREAM_DRAFT_UPDATE_INTERVAL_SECONDS,
    ) -> None:
        if self._disabled or not text or text == self._last_text:
            return
        now = time.monotonic()
        if now < self._retry_after_until:
            return
        if (
            not force
            and self._last_text
            and now - self._last_sent_at < min_interval_seconds
        ):
            return

        send_message_draft = getattr(self._bot, "send_message_draft", None)
        if send_message_draft is None:
            self._disabled = True
            return

        try:
            await send_message_draft(
                chat_id=self._chat_id,
                draft_id=self._draft_id,
                text=text,
                parse_mode="HTML",
            )
            self._last_text = text
            self._last_sent_at = now
        except TypeError:
            try:
                await send_message_draft(
                    chat_id=self._chat_id,
                    draft_id=self._draft_id,
                    text=text,
                )
                self._last_text = text
                self._last_sent_at = now
            except RetryAfter as exc:
                self._pause_for_retry_after(exc)
            except Exception:
                self._disabled = True
                logger.exception("telegram_draft_stream_failed")
        except RetryAfter as exc:
            self._pause_for_retry_after(exc)
        except Exception:
            self._disabled = True
            logger.exception("telegram_draft_stream_failed")

    def _pause_for_retry_after(self, exc: RetryAfter) -> None:
        retry_after = float(getattr(exc, "retry_after", 3.0) or 3.0)
        self._retry_after_until = time.monotonic() + retry_after + 0.5
        logger.warning(
            "telegram_draft_stream_rate_limited retry_after_seconds=%s",
            retry_after,
        )


async def _send_loading_drafts(streamer: _TelegramDraftStreamer) -> None:
    """Animate a lightweight Telegram draft until the first streamed token arrives."""
    states = (".", "..", "...")
    index = 0
    try:
        while True:
            await streamer.publish(
                states[index % len(states)],
                min_interval_seconds=0,
            )
            index += 1
            await asyncio.sleep(STREAM_LOADING_DRAFT_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("telegram_loading_draft_failed")


async def _send_processing_notices(message: object) -> None:
    """Send progress notes while the LLM call takes long enough to feel stuck."""
    try:
        await asyncio.sleep(PROCESSING_NOTICE_INITIAL_DELAY_SECONDS)
        reply_text = getattr(message, "reply_text", None)
        if reply_text is None:
            return
        await reply_text(PROCESSING_NOTICE_MESSAGE)
        while True:
            await asyncio.sleep(PROCESSING_NOTICE_INTERVAL_SECONDS)
            await reply_text(PROCESSING_NOTICE_REPEAT_MESSAGE)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("processing_notice_failed")


async def _finish_ignored_request(
    update: Update,
    request_id: str,
    message: str,
) -> None:
    await _ignore_with_reply(update, message)
    if update.effective_user:
        await request_state.finish(
            user_id=update.effective_user.id,
            request_id=request_id,
            status="ignored",
        )
