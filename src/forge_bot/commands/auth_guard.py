from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import has_current_policy_acceptance, is_admin, verify_user
from forge_bot.messages import build_message

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]
IDENTITY_UNAVAILABLE_MESSAGE = (
    "Identity checks are temporarily unavailable. Please try again in a moment."
)
INVITE_REQUIRED_MESSAGE = (
    "Access denied. Open your Telegram invite link to connect your identity."
)
ADMIN_LOGIN_REQUIRED_MESSAGE = (
    "Access denied. Please log in before using this admin command."
)
ADMINS_ONLY_MESSAGE = "Access denied. Admins only."
POLICY_REQUIRED_MESSAGE = build_message(
    "Please accept the current usage policy before continuing.",
    actions=("/policy", "/accept_policy", "/decline_policy"),
)


def require_login(func: Handler) -> Handler:
    # Keep the login guard reusable for commands and text-message routing.
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        if not await _require_linked_user(update, user_id, INVITE_REQUIRED_MESSAGE):
            return
        if not await _require_policy_acceptance(update, user_id):
            return

        await func(update, context)

    return wrapper


def require_linked_user(func: Handler) -> Handler:
    """Restrict a handler to Telegram users already linked to BotForge."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        if not await _require_linked_user(update, user_id, INVITE_REQUIRED_MESSAGE):
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
        if not await _require_linked_user(
            update,
            user_id,
            ADMIN_LOGIN_REQUIRED_MESSAGE,
        ):
            return
        if not await _require_admin(update, user_id):
            return
        if not await _require_policy_acceptance(update, user_id):
            return

        await func(update, context)

    return wrapper


async def _require_linked_user(
    update: Update,
    user_id: int,
    denial_message: str,
) -> bool:
    if not update.message:
        return False

    verified = verify_user(user_id)
    if verified is None:
        await update.message.reply_text(IDENTITY_UNAVAILABLE_MESSAGE)
        return False
    if not verified:
        await update.message.reply_text(denial_message)
        return False
    return True


async def _require_admin(update: Update, user_id: int) -> bool:
    if not update.message:
        return False

    admin = is_admin(user_id)
    if admin is None:
        await update.message.reply_text(IDENTITY_UNAVAILABLE_MESSAGE)
        return False
    if not admin:
        await update.message.reply_text(ADMINS_ONLY_MESSAGE)
        return False
    return True


async def _require_policy_acceptance(update: Update, user_id: int) -> bool:
    if not update.message:
        return False

    policy_accepted = has_current_policy_acceptance(user_id)
    if policy_accepted is None:
        await update.message.reply_text(IDENTITY_UNAVAILABLE_MESSAGE)
        return False
    if not policy_accepted:
        await update.message.reply_text(POLICY_REQUIRED_MESSAGE)
        return False
    return True
