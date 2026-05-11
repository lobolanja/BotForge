from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import logout_user, redeem_invite_token, status_user

from .auth_guard import require_login
from .policy import policy_prompt


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    args = context.args or []

    await update.message.reply_text(
        "Welcome to BotForge. Open your invite link to authenticate."
    )

    redemption = redeem_invite_token(args[0], update.effective_user.id)
    if redemption.status == "success":
        await update.message.reply_text(f"Invite accepted.\n\n{policy_prompt()}")
    elif redemption.status == "already_linked":
        await update.message.reply_text("This Telegram account is already linked.")
    elif redemption.status == "expired":
        await update.message.reply_text("This invite link has expired.")
    elif redemption.status == "used":
        await update.message.reply_text("This invite link has already been used.")
    elif redemption.status == "invalid":
        await update.message.reply_text("This invite link is invalid.")
    else:
        await update.message.reply_text(
            "Invite authentication is temporarily unavailable."
        )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = status_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"You are logged in as: {user['username']}\nUse /logout to log out."
        )
    else:
        await update.message.reply_text("You are not logged in.")


@require_login
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    # Keep logout idempotent from Telegram's perspective: report DB update success.
    if logout_user(update.effective_user.id):
        await update.message.reply_text("Session closed successfully.")
    else:
        await update.message.reply_text("Failed to close the session.")
