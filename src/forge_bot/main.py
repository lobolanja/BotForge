import logging

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

logger = logging.getLogger(__name__)
MAX_CONCURRENT_UPDATES = 8
COMMAND_HANDLERS = (
    ("greet", greet),
    ("ping", ping),
    ("help", help_command),
    ("start", start),
    ("unknown", unknown_command),
    ("translate", translate),
    ("time", time),
    ("status", status),
    ("policy", policy),
    ("accept_policy", accept_policy),
    ("decline_policy", decline_policy),
    ("invite", invite),
    ("campaign_invite", campaign_invite),
)


def setup_logging() -> None:
    """Configure process logging for local and container runtime diagnostics."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def log_startup_configuration() -> None:
    """Log a secret-free runtime summary useful during beta startup."""
    settings = get_settings()
    logger.info(
        "startup_config env=%s db_host=%s db_port=%s db_name=%s "
        "ollama_host=%s ollama_model=%s bot_profile=%s ai_timeout_seconds=%s "
        "ai_max_response_chars=%s max_message_chars=%s "
        "user_messages_per_minute=%s user_ai_requests_per_hour=%s "
        "chat_messages_per_minute=%s global_active_ai_requests=%s "
        "global_ai_queue_size=%s admin_invites_per_hour=%s",
        settings.botforge_env,
        settings.db_host,
        settings.db_port,
        settings.db_name,
        settings.ollama_host,
        settings.ollama_model,
        settings.bot_profile,
        settings.ai_timeout_seconds,
        settings.ai_max_response_chars,
        settings.max_message_chars,
        settings.user_messages_per_minute,
        settings.user_ai_requests_per_hour,
        settings.chat_messages_per_minute,
        settings.global_active_ai_requests,
        settings.global_ai_queue_size,
        settings.admin_invites_per_hour,
    )


def main() -> None:
    """Start the Telegram bot after validating shared and bot-specific config."""
    setup_logging()
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

    log_startup_configuration()

    # Process updates concurrently so in-flight per-user request state can
    # respond immediately when a user sends a second message while the AI works.
    bot = (
        Application.builder()
        .token(settings.telegram_token)
        .concurrent_updates(MAX_CONCURRENT_UPDATES)
        .build()
    )

    recovery = recover_unfinished_messages()
    logger.info(
        "inbound_message_recovery retried=%s expired=%s failed=%s",
        recovery.retried,
        recovery.expired,
        recovery.failed,
    )

    # Persist supported messages before command or AI handlers do expensive work.
    bot.add_handler(MessageHandler(filters.ALL, record_inbound_update), group=-1)

    for command, handler in COMMAND_HANDLERS:
        bot.add_handler(CommandHandler(command, handler))

    # Unknown commands are handled after known commands fail to match.
    bot.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Non-command text is routed to the AI conversation flow.
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_ia))

    # Log a short startup signal for Docker and local development.
    logger.info("bot_polling_started concurrent_updates=%s", MAX_CONCURRENT_UPDATES)
    bot.run_polling()


# Run the app only when this module is executed directly.
if __name__ == "__main__":
    main()
