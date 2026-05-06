import os

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .commands import (
    greet,
    help_command,
    login,
    logout,
    ping,
    status,
    time,
    translate,
    unknown_command,
)
from .router import ask_ia

# Loads environment variables from the .env file into the system
load_dotenv()


def main():
    # Retrieve the token from the environment variables
    token = os.getenv("TELEGRAM_TOKEN")

    if not token:
        print("Error: TELEGRAM_TOKEN not found in .env file")
        return

    # This is the central registry for the Telegram command handlers.
    bot = Application.builder().token(token).build()

    bot.add_handler(CommandHandler("greet", greet))
    bot.add_handler(CommandHandler("ping", ping))
    bot.add_handler(CommandHandler("help", help_command))
    bot.add_handler(CommandHandler("unknown", unknown_command))
    bot.add_handler(CommandHandler("translate", translate))
    bot.add_handler(CommandHandler("time", time))
    bot.add_handler(CommandHandler("login", login))
    bot.add_handler(CommandHandler("status", status))
    bot.add_handler(CommandHandler("logout", logout))

    # Unknown commands are handled after known commands fail to match.
    bot.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Non-command text is routed to the AI conversation flow.
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_ia))

    # to make sure it is running
    print("Bot in execution...")
    bot.run_polling()


# Entry point: ensures main() only runs if script is executed directly
if __name__ == "__main__":
    main()
