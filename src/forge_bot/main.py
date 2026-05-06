import os

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .bot_profile import BotProfileError, load_active_bot_profile
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
from .config import SettingsError, get_settings
from .router import ask_ia

# Load .env values before validating process configuration.
load_dotenv()


def main():
    """Start the Telegram bot after validating shared and bot-specific config."""
    try:
        settings = get_settings()
        load_active_bot_profile(
            settings.bot_profile,
            settings.bot_profiles_dir,
        )
    except SettingsError as error:
        raise SystemExit(f"Configuration error: {error}") from None
    except BotProfileError as error:
        raise SystemExit(f"Bot profile error: {error}") from None

    # This is the central registry for Telegram command handlers.
    bot = Application.builder().token(settings.telegram_token).build()

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

    # Log a short startup signal for Docker and local development.
    print("Bot in execution...")
    bot.run_polling()


# Run the app only when this module is executed directly.
if __name__ == "__main__":
    main()
