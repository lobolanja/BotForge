from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .bot_profile import BotProfileError, load_active_bot_profile
from .commands.auth import start, status
from .commands.campaign_invite import campaign_invite
from .commands.greet import greet
from .commands.help import help_command
from .commands.invite import invite
from .commands.ping import ping
from .commands.policy import accept_policy, decline_policy, policy
from .commands.time import time
from .commands.translate import translate
from .commands.unknown import unknown_command
from .config import SettingsError, get_settings
from .message_store import recover_unfinished_messages
from .router import ask_ia, record_inbound_update


def main() -> None:
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

    recovery = recover_unfinished_messages()
    print(
        "Inbound message recovery: "
        f"retried={recovery.retried} "
        f"expired={recovery.expired} "
        f"failed={recovery.failed}"
    )

    # Persist supported messages before command or AI handlers do expensive work.
    bot.add_handler(MessageHandler(filters.ALL, record_inbound_update), group=-1)

    bot.add_handler(CommandHandler("greet", greet))
    bot.add_handler(CommandHandler("ping", ping))
    bot.add_handler(CommandHandler("help", help_command))
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("unknown", unknown_command))
    bot.add_handler(CommandHandler("translate", translate))
    bot.add_handler(CommandHandler("time", time))
    bot.add_handler(CommandHandler("status", status))
    bot.add_handler(CommandHandler("policy", policy))
    bot.add_handler(CommandHandler("accept_policy", accept_policy))
    bot.add_handler(CommandHandler("decline_policy", decline_policy))
    bot.add_handler(CommandHandler("invite", invite))
    bot.add_handler(CommandHandler("campaign_invite", campaign_invite))

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
