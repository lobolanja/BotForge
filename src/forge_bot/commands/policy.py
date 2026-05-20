from typing import Literal, cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from forge_bot.config import get_settings
from forge_bot.database import (
    accept_current_policy,
    current_policy_versions,
    decline_current_policy,
    has_current_policy_acceptance,
    verify_user,
)
from forge_bot.messages import build_message

IDENTITY_UNAVAILABLE_MESSAGE = (
    "Identity checks are temporarily unavailable. Please try again in a moment."
)
ACCEPT_UNLINKED_MESSAGE = build_message(
    "I could not accept the policy because your identity is not linked.",
    actions=("/start",),
)
DECLINE_UNLINKED_MESSAGE = build_message(
    "I could not decline the policy because your identity is not linked.",
    actions=("/start",),
)
ACCEPT_SUCCESS_MESSAGE = build_message(
    "Policy accepted.",
    details=(("Next step", "You can now send me a message"),),
)
ACCEPT_ALREADY_ACCEPTED_MESSAGE = "You already accepted the current policy."
ACCEPT_UNAVAILABLE_MESSAGE = (
    "Policy acceptance is temporarily unavailable. Please try again in a moment."
)
DECLINE_SUCCESS_MESSAGE = build_message(
    "Policy declined.",
    details=(
        (
            "What happens next",
            "Protected chat messages will stay unavailable until you accept the policy",
        ),
    ),
    actions=("/policy", "/accept_policy", "/privacy"),
)
DECLINE_UNAVAILABLE_MESSAGE = (
    "Policy decline is temporarily unavailable. Please try again in a moment."
)
POLICY_ACCEPT_CALLBACK = "policy:accept"
POLICY_DECLINE_CALLBACK = "policy:decline"

PolicyActionStatus = Literal[
    "accepted",
    "already_accepted",
    "declined",
    "not_linked",
    "database_unavailable",
]

POLICY_PROMPT_INTRO = (
    "Please review the current BotForge usage policy before continuing.\n\n"
    "By accepting, you confirm that you understand how the bot may store "
    "messages, memory, and optional analytics data according to the current "
    "policy."
)
POLICY_COMMAND_FALLBACK = build_message(
    "Choose how you want to continue.",
    actions=("/accept_policy", "/decline_policy", "/privacy"),
)


def policy_action_keyboard() -> InlineKeyboardMarkup:
    """Build the inline keyboard used in onboarding and /policy prompts."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Accept policy",
                    callback_data=POLICY_ACCEPT_CALLBACK,
                ),
                InlineKeyboardButton(
                    "Decline",
                    callback_data=POLICY_DECLINE_CALLBACK,
                ),
            ]
        ]
    )


def policy_prompt() -> str:
    """Build the short first-layer policy notice shown inside Telegram."""
    versions = current_policy_versions()
    return (
        f"{POLICY_PROMPT_INTRO}\n\n"
        f"Policy version: {versions.policy_version}\n"
        f"Privacy notice version: {versions.privacy_notice_version}\n\n"
        f"{POLICY_COMMAND_FALLBACK}"
    )


async def policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    settings = get_settings()
    versions = current_policy_versions()
    text = (
        "BotForge usage policy\n\n"
        f"Policy version: {versions.policy_version}\n"
        f"Privacy notice version: {versions.privacy_notice_version}\n\n"
        "BotForge processes Telegram messages to provide AI-assisted replies. "
        "It can be wrong and does not replace professional judgment.\n\n"
        "Do not send illegal content, credentials, secrets, or unnecessary "
        "sensitive personal data.\n\n"
        "BotForge may store your Telegram user id, messages, timestamps, "
        "interactions, conversation memory, and technical logs needed to "
        "operate the service. Optional analytics or training consent is "
        "separate and defaults to off.\n\n"
        "Do you accept this policy?\n\n"
        f"{POLICY_COMMAND_FALLBACK}"
    )
    if settings.bot_policy_url:
        text = f"{text}\n\nFull policy: {settings.bot_policy_url}"

    await update.message.reply_text(text, reply_markup=policy_action_keyboard())


async def accept_policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    status = accept_current_policy_for_user(update.effective_user.id)
    await update.message.reply_text(_accept_policy_message(status))


async def decline_policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    status = decline_current_policy_for_user(update.effective_user.id)
    await update.message.reply_text(_decline_policy_message(status))


async def accept_policy_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    if not update.effective_user or not query.message:
        return

    message = cast(Message, query.message)
    await _clear_policy_action_keyboard(message)
    status = accept_current_policy_for_user(update.effective_user.id)
    await message.reply_text(_accept_policy_message(status))


async def decline_policy_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    if not update.effective_user or not query.message:
        return

    message = cast(Message, query.message)
    await _clear_policy_action_keyboard(message)
    status = decline_current_policy_for_user(update.effective_user.id)
    await message.reply_text(_decline_policy_message(status))


def accept_current_policy_for_user(telegram_user_id: int) -> PolicyActionStatus:
    """Apply current policy acceptance rules for commands and button callbacks."""
    verified = verify_user(telegram_user_id)
    if verified is None:
        return "database_unavailable"
    if not verified:
        return "not_linked"

    already_accepted = has_current_policy_acceptance(telegram_user_id)
    if already_accepted is None:
        return "database_unavailable"
    if already_accepted:
        return "already_accepted"

    if accept_current_policy(telegram_user_id):
        return "accepted"
    return "database_unavailable"


def decline_current_policy_for_user(telegram_user_id: int) -> PolicyActionStatus:
    """Apply current policy decline rules for commands and button callbacks."""
    verified = verify_user(telegram_user_id)
    if verified is None:
        return "database_unavailable"
    if not verified:
        return "not_linked"

    if decline_current_policy(telegram_user_id):
        return "declined"
    return "database_unavailable"


def _accept_policy_message(status: PolicyActionStatus) -> str:
    messages = {
        "accepted": ACCEPT_SUCCESS_MESSAGE,
        "already_accepted": ACCEPT_ALREADY_ACCEPTED_MESSAGE,
        "not_linked": ACCEPT_UNLINKED_MESSAGE,
        "database_unavailable": ACCEPT_UNAVAILABLE_MESSAGE,
    }
    return messages.get(status, IDENTITY_UNAVAILABLE_MESSAGE)


def _decline_policy_message(status: PolicyActionStatus) -> str:
    messages = {
        "declined": DECLINE_SUCCESS_MESSAGE,
        "not_linked": DECLINE_UNLINKED_MESSAGE,
        "database_unavailable": DECLINE_UNAVAILABLE_MESSAGE,
    }
    return messages.get(status, IDENTITY_UNAVAILABLE_MESSAGE)


async def _clear_policy_action_keyboard(message: Message) -> None:
    """Remove stale inline actions after a policy button is used."""
    await message.edit_reply_markup(reply_markup=None)
