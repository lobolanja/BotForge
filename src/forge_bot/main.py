from telegram.ext import Application, CommandHandler, MessageHandler, filters
from . import (
    ask_ia,
    greet,
    ping,
    help_command,
    unknown_command,
    translate,
    time,
    login,
    status,
    logout,
)
import os
from dotenv import load_dotenv

# Loads environment variables from the .env file into the system
load_dotenv()


def main():
    # Retrieve the token from the environment variables
    token = os.getenv("TELEGRAM_TOKEN")

    if not token:
        print("Error: TELEGRAM_TOKEN not found in .env file")
        return

    # variable that contains the bot that is the one you are working with
    bot = Application.builder().token(token).build()

    # call to the 'saludar' command
    bot.add_handler(CommandHandler("greet", greet))

    # call to the 'ping' command
    bot.add_handler(CommandHandler("ping", ping))

    # call to the 'help' command
    bot.add_handler(CommandHandler("help", help_command))

    # call to the 'unknown' command
    bot.add_handler(CommandHandler("unknown", unknown_command))

    # call to the 'translate' command
    bot.add_handler(CommandHandler("translate", translate))

    # call to the 'time' command
    bot.add_handler(CommandHandler("time", time))

    # call to the 'login' command
    bot.add_handler(CommandHandler("login", login))

    # call to the 'status' command
    bot.add_handler(CommandHandler("status", status))

    # call to the 'logout' command
    bot.add_handler(CommandHandler("logout", logout))

    # call to the 'unknown' command
    bot.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # call to the ia
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_ia))

    # to make sure it is running
    print("Bot in execution...")
    bot.run_polling()


# Entry point: ensures main() only runs if script is executed directly
if __name__ == "__main__":
    main()
