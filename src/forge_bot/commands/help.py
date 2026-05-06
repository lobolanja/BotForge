from telegram import Update
from telegram.ext import ContextTypes


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    # This text is the single user-facing list of currently supported commands.
    help_text = (
        "Available commands:\n"
        "/greet - Greet the user\n"
        "/ping - Check the bot's latency\n"
        "/translate - Translate text to another language\n"
        "/time - Show the current time\n"
        "/help - Show the available commands\n"
        "/login [password] - Log in to the system\n"
        "/logout - Log out of the system\n"
        "/status - Check your login status\n"
    )
    await update.message.reply_text(help_text)
