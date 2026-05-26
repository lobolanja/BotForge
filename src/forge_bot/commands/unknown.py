from telegram import Update
from telegram.ext import ContextTypes

from .auth_guard import require_login


@require_login
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Command not found. Use /help to see the available commands."
    )
