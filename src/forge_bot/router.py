from telegram import Update
from telegram.ext import ContextTypes

from . import engine
from .commands.auth_guard import require_login
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
from .rate_limits import LimitDecision, abuse_limiter
from .request_state import REQUEST_WAITING_MESSAGE, request_state


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
            "I could not store your message safely. Please try again in a moment."
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
        )

        # Send the generated answer back into the same chat.
        await update.message.reply_text(answer)
        mark_answered(update.update_id)
        finished_status = "answered"
    except Exception as exc:
        mark_failed(update.update_id, type(exc).__name__)
        await update.message.reply_text(
            "Sorry, I could not finish that message. It has been stored for review."
        )
    finally:
        await ai_lease.release()
        await request_state.finish(
            user_id=update.effective_user.id,
            request_id=active_request.request_id,
            status=finished_status,
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
