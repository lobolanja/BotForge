import time as time_module

from telegram import Update
from telegram.ext import ContextTypes

from .auth_guard import require_login


@require_login
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    # Measure the round trip for editing a Telegram message as a quick bot check.
    start = time_module.time()
    msg = await update.message.reply_text("Calculating latency...")
    end = time_module.time()

    latencia_ms = round((end - start) * 1000)
    await msg.edit_text(f"Latency: `{latencia_ms}ms`", parse_mode="Markdown")
