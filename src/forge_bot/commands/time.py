from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes


async def time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    await update.message.reply_text(f"Current time: {now}")
