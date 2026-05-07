from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import login_user, logout_user, redeem_invite_token, status_user

from .auth_guard import require_login


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Welcome to BotForge. Open your invite link to authenticate."
        )
        return

    redemption = redeem_invite_token(args[0], update.effective_user.id)
    if redemption.status == "success":
        await update.message.reply_text(
            "Invite accepted. You can now chat with BotForge."
        )
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


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Link the Telegram account to an existing database user after password check.
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Password login is deprecated. Use your Telegram invite link."
        )
        return

    username, password = args[0], args[1]
    if login_user(username, password, update.effective_user.id):
        await update.message.reply_text(f"Welcome {username}! You have logged in.")
    else:
        await update.message.reply_text("Invalid username or password.")


async def login_disabled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Password login is disabled. Open your Telegram invite link to authenticate."
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
