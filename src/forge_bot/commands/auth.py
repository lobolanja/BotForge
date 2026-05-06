from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import login_user, logout_user, status_user

from .auth_guard import require_login


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Link the Telegram account to an existing database user after password check.
    if len(context.args) < 2:
        await update.message.reply_text("Usage: '/login username password'")
        return

    username, password = context.args[0], context.args[1]
    if login_user(username, password, update.effective_user.id):
        await update.message.reply_text(f"✅ Welcome {username}! You have logged in.")
    else:
        await update.message.reply_text("❌ Invalid username or password.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = status_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"✅ You are logged in as: {user['username']}\nUse /logout to log out."
        )
    else:
        await update.message.reply_text("❌ You are not logged in.")


@require_login
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Keep logout idempotent from Telegram's perspective: report DB update success.
    if logout_user(update.effective_user.id):
        await update.message.reply_text("✅ Session closed successfully.")
    else:
        await update.message.reply_text("❌ Failed to close the session.")
