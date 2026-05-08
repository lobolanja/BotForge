from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.config import get_settings
from forge_bot.database import (
    accept_current_policy,
    current_policy_versions,
    decline_current_policy,
    verify_user,
)

POLICY_SUMMARY = """Before you start, you must accept the BotForge usage policy.

Summary:
- This bot answers with AI and can make mistakes.
- Do not send secrets or information you do not want processed.
- We store data needed to provide the service.
- Conversation memory may be used to improve your answers.
- Analytics or training consent is handled separately and is not enabled here.

Use /policy to read the policy, then /accept_policy or /decline_policy."""


def policy_prompt() -> str:
    """Build the short first-layer policy notice shown inside Telegram."""
    versions = current_policy_versions()
    return (
        f"{POLICY_SUMMARY}\n\n"
        f"Policy version: {versions.policy_version}\n"
        f"Privacy notice version: {versions.privacy_notice_version}"
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
        "This bot processes Telegram messages to provide AI-assisted replies. "
        "It can be wrong and does not replace professional judgment. Do not "
        "send illegal content, credentials, secrets, or unnecessary sensitive "
        "personal data. BotForge may store your Telegram user id, messages, "
        "timestamps, interactions, uploaded files if enabled, and technical "
        "logs needed to operate the service. Conversation memory may be used "
        "to provide better answers. Optional analytics or training consent is "
        "separate and defaults to off. "
        "\n\nDo you accept this policy?"
        "\nUse /accept_policy to accept or /decline_policy to decline."
    )
    if settings.bot_policy_url:
        text = f"{text}\n\nFull policy: {settings.bot_policy_url}"

    await update.message.reply_text(text)


async def accept_policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    if not verify_user(update.effective_user.id):
        await update.message.reply_text(
            "Open your Telegram invite link before accepting the policy."
        )
        return

    if accept_current_policy(update.effective_user.id):
        await update.message.reply_text("Policy accepted. You can now use BotForge.")
    else:
        await update.message.reply_text("Policy acceptance is temporarily unavailable.")


async def decline_policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    if not verify_user(update.effective_user.id):
        await update.message.reply_text(
            "Open your Telegram invite link before declining the policy."
        )
        return

    if decline_current_policy(update.effective_user.id):
        await update.message.reply_text(
            "Policy declined. BotForge cannot be used until you accept /policy."
        )
    else:
        await update.message.reply_text("Policy decline is temporarily unavailable.")
