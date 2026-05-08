from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import has_current_policy_acceptance, is_admin, verify_user

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]


def require_login(func: Handler) -> Handler:
    # Keep the login guard reusable for commands and text-message routing.
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        if not verify_user(user_id):
            await update.message.reply_text(
                "Access denied. Open your Telegram invite link to authenticate."
            )
            return
        if not has_current_policy_acceptance(user_id):
            await update.message.reply_text(
                "Please accept the current usage policy before using BotForge. "
                "Use /policy and then /accept_policy."
            )
            return

        await func(update, context)

    return wrapper


def admin_required(func: Handler) -> Handler:
    """Restrict a Telegram command handler to logged-in admin users."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        if not verify_user(user_id):
            await update.message.reply_text(
                "Access denied. Please log in before using this admin command."
            )
            return
        if not is_admin(user_id):
            await update.message.reply_text("Access denied. Admins only.")
            return

        if not has_current_policy_acceptance(user_id):
            await update.message.reply_text(
                "Please accept the current usage policy before using BotForge. "
                "Use /policy and then /accept_policy."
            )
            return

        await func(update, context)

    return wrapper
