"""User-facing privacy and data deletion controls."""

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import (
    clear_memory_for_telegram_user,
    confirm_user_deletion,
    request_user_deletion,
)

PRIVACY_TEXT = (
    "BotForge data controls\n\n"
    "BotForge stores your Telegram identity after invite redemption, policy "
    "acceptance status, and operational message state needed to recover from "
    "failures.\n\n"
    "If memory is enabled, BotForge stores recent conversation context and "
    "compacted memory for personalization. If analytics or file upload "
    "features are enabled later, BotForge will document those records and "
    "their deletion behavior before use.\n\n"
    "Available commands:\n"
    "/memory_clear - Clear personalization memory.\n"
    "/delete_my_data - Start broader account data deletion."
)

DELETE_EXPLANATION = (
    "This starts broader deletion for your BotForge data.\n\n"
    "Beta deletion will remove your Telegram identity link, clear "
    "personalization memory, and anonymize operational message data that is "
    "tied to your Telegram account. Minimal invite, policy, security, and "
    "backup records may remain as documented operational audit.\n\n"
    "After deletion, protected bot features will stop working until you redeem "
    "a new invite.\n\n"
    "To confirm, send /delete_my_data CONFIRM."
)


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain stored data categories and available controls."""
    if not update.message:
        return

    await update.message.reply_text(PRIVACY_TEXT)


async def memory_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear personalization memory for the linked Telegram user."""
    if not update.message or not update.effective_user:
        return

    result = clear_memory_for_telegram_user(update.effective_user.id)
    if result is None:
        await update.message.reply_text(
            "No linked BotForge account was found to clear."
        )
        return

    await update.message.reply_text(
        "Personalization memory has been cleared for your account."
    )


async def delete_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Request or confirm broader beta deletion for the linked Telegram user."""
    if not update.message or not update.effective_user:
        return

    args = [arg.strip() for arg in (context.args or []) if arg.strip()]
    if len(args) == 1 and args[0].upper() == "CONFIRM":
        result = confirm_user_deletion(update.effective_user.id)
        if result.status == "deleted":
            await update.message.reply_text(
                "Your BotForge data deletion is complete. "
                "Your Telegram identity is no longer linked."
            )
            return
        if result.status == "manual_review_requested":
            await update.message.reply_text(
                "Your deletion request is confirmed and queued for manual owner "
                "review because this account has administrator access."
            )
            return
        if result.status == "not_linked":
            await update.message.reply_text("No linked BotForge account was found.")
            return

        await update.message.reply_text(
            "BotForge could not complete deletion right now. Please try again later."
        )
        return

    if args:
        await update.message.reply_text(
            "Usage: /delete_my_data or /delete_my_data CONFIRM"
        )
        return

    result = request_user_deletion(update.effective_user.id)
    if result.status == "not_linked":
        await update.message.reply_text("No linked BotForge account was found.")
        return
    if result.status == "db_error":
        await update.message.reply_text(
            "BotForge could not start deletion right now. Please try again later."
        )
        return

    await update.message.reply_text(DELETE_EXPLANATION)
