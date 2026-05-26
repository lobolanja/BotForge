from telegram import Update
from telegram.ext import ContextTypes

from .auth_guard import require_login


@require_login
async def greet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = update.effective_user.first_name
    await update.message.reply_text("Hello " + user)
