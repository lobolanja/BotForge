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
    if current_status in {"persisted", "received", "failed"}:
        mark_queued(update.update_id)
    elif current_status == "processing":
        return

    claimed = mark_processing(update.update_id)
    if claimed is None:
        return

    # Extract the current Telegram message and the visible user name.
    message = update.message.text or ""
    user = update.effective_user.first_name

    try:
        # Show Telegram's typing indicator while the LLM response is generated.
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )

        # Delegate prompt assembly and Ollama communication to the engine module.
        answer = await engine.answer(user, message)

        # Send the generated answer back into the same chat.
        await update.message.reply_text(answer)
        mark_answered(update.update_id)
    except Exception as exc:
        mark_failed(update.update_id, type(exc).__name__)
        await update.message.reply_text(
            "Sorry, I could not finish that message. It has been stored for review."
        )
