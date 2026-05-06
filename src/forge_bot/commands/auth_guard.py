from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import verify_user


def require_login(func):
    # Keep the login guard reusable for commands and text-message routing.
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        user_id = update.effective_user.id
        if not verify_user(user_id):
            await update.message.reply_text(
                "❌ Access denied. Please log in using /login [password] "
                "to use this command."
            )
            return
        return await func(update, context)

    return wrapper
