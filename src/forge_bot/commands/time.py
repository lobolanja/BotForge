from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from .auth_guard import require_login


@require_login
async def time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    now = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    await update.message.reply_text(f"Current time: {now}")
