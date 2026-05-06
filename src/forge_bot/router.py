from telegram import Update
from telegram.ext import ContextTypes

from . import engine
from .commands import require_login


@require_login
async def ask_ia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route authenticated plain-text Telegram messages to the AI engine."""
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    # Extract the current Telegram message and the visible user name.
    message = update.message.text or ""
    user = update.effective_user.first_name

    # Show Telegram's typing indicator while the LLM response is generated.
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    # Delegate prompt assembly and Ollama communication to the engine module.
    answer = await engine.answer(user, message)

    # Send the generated answer back into the same chat.
    await update.message.reply_text(answer)
