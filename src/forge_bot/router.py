import logging
from collections.abc import Sequence

from telegram import Update
from telegram.ext import ContextTypes

from . import engine
from .bot_profile import BotProfile
from .commands.auth_guard import require_login
from .config import get_settings
from .database import get_user_by_telegram_id
from .memory_store import add_successful_turn, get_memory_context
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
    internal_user = (
        get_user_by_telegram_id(update.effective_user.id) if memory_is_enabled else None
    )
    memory_context = None
    if internal_user and memory_is_enabled:
        memory_context = get_memory_context(
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

        # Delegate prompt assembly and LLM provider selection to the engine module.
        answer = await engine.answer(
            user,
            message,
            profile=active_profile,
            request_id=processing_request.request_id,
            queue_wait_seconds=processing_request.queue_wait_seconds,
            compacted_user_memory=(
                memory_context.compacted_user_memory if memory_context else None
            ),
            recent_conversation_messages=(
                memory_context.recent_conversation_messages if memory_context else []
            ),
        )

        # Send the generated answer back into the same chat.
        await update.message.reply_text(answer)
        mark_answered(update.update_id)
        if internal_user and memory_is_enabled:
            await _remember_successful_turn(
                internal_user_id=int(internal_user["id"]),
                bot_profile_id=active_profile.bot_profile_id,
                user_message=message,
                assistant_message=answer,
                telegram_chat_id=update.effective_chat.id,
                telegram_message_id=getattr(update.message, "message_id", None),
                inbound_message_id=claimed.get("id") if claimed else None,
                request_id=processing_request.request_id,
                profile=active_profile,
            )
        finished_status = "answered"
    except Exception as exc:
        mark_failed(update.update_id, type(exc).__name__)
        await update.message.reply_text(
            "I could not finish that message right now. It has been stored for "
            "review. Please try again in a moment."
        )
    finally:
        await ai_lease.release()
        await request_state.finish(
            user_id=update.effective_user.id,
            request_id=active_request.request_id,
            status=finished_status,
        )


def _memory_enabled(profile: BotProfile) -> bool:
    if not profile.memory_enabled:
        return False
    return get_settings().memory_enabled


async def _remember_successful_turn(
    *,
    internal_user_id: int,
    bot_profile_id: str,
    user_message: str,
    assistant_message: str,
    telegram_chat_id: int | None,
    telegram_message_id: int | None,
    inbound_message_id: int | None,
    request_id: str,
    profile: BotProfile,
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
        await add_successful_turn(
            user_id=internal_user_id,
            bot_profile_id=bot_profile_id,
            user_message=user_message,
            assistant_message=assistant_message,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            inbound_message_id=inbound_message_id,
            request_id=request_id,
            summarizer=summarize,
        )
    except Exception:
        # The user already received the answer. Memory must not turn that into
        # a failed inbound message or leak raw content into logs.
        logger.exception(
            "memory_store_after_answer_failed request_id=%s user_id=%s",
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
