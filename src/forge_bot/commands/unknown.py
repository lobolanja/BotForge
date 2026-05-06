from telegram import Update
from telegram.ext import ContextTypes


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Command not found. Use /help to see the available commands."
    )
