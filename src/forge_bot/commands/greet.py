from telegram import Update
from telegram.ext import ContextTypes


async def greet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = update.effective_user.first_name
    await update.message.reply_text("Hello " + user)
