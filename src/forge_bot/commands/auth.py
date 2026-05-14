from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import redeem_invite_token, status_user

from .policy import policy_prompt

INVITE_PROMPT = "Welcome to BotForge. Open your invite link to connect your identity."
ALREADY_LINKED_START = (
    "Welcome back to BotForge. This Telegram account is already linked."
)
REDEMPTION_FAILURE_MESSAGES = {
    "already_linked": "This Telegram account is already linked.",
    "expired": "This invite link has expired.",
    "used": "This invite link has already been used.",
    "campaign_full": "This campaign invite link is full.",
    "invalid": "This invite link is invalid.",
}
REDEMPTION_UNAVAILABLE = "Invite identity connection is temporarily unavailable."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    args = context.args or []

    if not args:
        user = status_user(update.effective_user.id)
        if user:
            await update.message.reply_text(ALREADY_LINKED_START)
            return
        await update.message.reply_text(INVITE_PROMPT)
        return

    await update.message.reply_text(INVITE_PROMPT)
    await _reply_to_invite_redemption(update, args[0], update.effective_user.id)


async def _reply_to_invite_redemption(
    update: Update,
    token: str,
    telegram_id: int,
) -> None:
    if not update.message:
        return

    redemption = redeem_invite_token(token, telegram_id)
    if redemption.status == "success":
        await update.message.reply_text(f"Invite accepted.\n\n{policy_prompt()}")
        return

    message = REDEMPTION_FAILURE_MESSAGES.get(
        redemption.status,
        REDEMPTION_UNAVAILABLE,
    )
    await update.message.reply_text(message)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = status_user(update.effective_user.id)
    if user:
        email = user.get("email")
        if email:
            await update.message.reply_text(
                f"Your Telegram identity is linked to {email} "
                f"with role: {user['role']}."
            )
            return
        await update.message.reply_text(
            f"Your Telegram identity is linked with role: {user['role']}."
        )
    else:
        await update.message.reply_text("Your Telegram identity is not linked yet.")
