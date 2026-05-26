import logging
from dataclasses import dataclass
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .bot_profile import BotProfileError, load_active_bot_profile
from .commands.admin_memory import admin_memory, admin_users
from .commands.auth import start, status
from .commands.campaign_invite import campaign_invite
from .commands.get_plan import get_plan
from .commands.greet import greet
from .commands.help import help_command
from .commands.invite import invite
from .commands.ping import ping
from .commands.policy import (
    POLICY_ACCEPT_CALLBACK,
    POLICY_DECLINE_CALLBACK,
    accept_policy,
    accept_policy_callback,
    decline_policy,
    decline_policy_callback,
    policy,
)
from .commands.privacy import delete_my_data, memory_clear, privacy
from .commands.set_plan import set_plan
from .commands.time import time
from .commands.translate import translate
from .commands.unknown import unknown_command
from .config import SettingsError, get_settings
from .message_store import (
    fail_queued_message,
    fail_unrecoverable_queued_messages,
    list_recoverable_queued_messages,
    mark_failed,
    recover_unfinished_messages,
)
from .router import ask_ia, record_inbound_update

logger = logging.getLogger(__name__)
MAX_CONCURRENT_UPDATES = 8
RECOVERY_BATCH_SIZE = 100
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
    ("privacy", privacy),
    ("memory_clear", memory_clear),
    ("delete_my_data", delete_my_data),
    ("admin_users", admin_users),
    ("admin_memory", admin_memory),
    ("set_plan", set_plan),
    ("get_plan", get_plan),
    ("invite", invite),
    ("campaign_invite", campaign_invite),
)


@dataclass(frozen=True)
class StartupQueueDrainSummary:
    replayed: int
    failed_unrecoverable: int
    failed_replay: int


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
        "global_ai_queue_size=%s admin_invites_per_hour=%s "
        "memory_enabled=%s memory_recent_messages=%s "
        "memory_compaction_trigger_messages=%s",
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
        settings.memory_enabled,
        settings.memory_recent_messages,
        settings.memory_compaction_trigger_messages,
    )


async def recover_and_drain_queued_messages(application: Any) -> None:
    """Recover unfinished rows and replay queued Telegram updates after startup."""
    recovery = recover_unfinished_messages()
    logger.info(
        "inbound_message_recovery retried=%s expired=%s failed=%s",
        recovery.retried,
        recovery.expired,
        recovery.failed,
    )

    drain = await drain_recovered_queued_messages(application)
    logger.info(
        "inbound_message_recovery_drain replayed=%s failed_unrecoverable=%s "
        "failed_replay=%s",
        drain.replayed,
        drain.failed_unrecoverable,
        drain.failed_replay,
    )


async def drain_recovered_queued_messages(application: Any) -> StartupQueueDrainSummary:
    """Replay queued text messages or fail rows that cannot be safely replayed."""
    failed_unrecoverable = fail_unrecoverable_queued_messages(
        "Queued message cannot be reconstructed during startup recovery"
    )
    replayed = 0
    failed_replay = 0
    seen_update_ids: set[int] = set()

    while True:
        queued_messages = list_recoverable_queued_messages(limit=RECOVERY_BATCH_SIZE)
        queued_messages = [
            message
            for message in queued_messages
            if message.telegram_update_id not in seen_update_ids
        ]
        if not queued_messages:
            break

        for message in queued_messages:
            seen_update_ids.add(message.telegram_update_id)
            try:
                if message.raw_update is None:
                    raise ValueError("missing raw update")
                update = Update.de_json(message.raw_update, application.bot)
                await application.process_update(update)
                replayed += 1
            except Exception as exc:
                logger.exception(
                    "inbound_message_recovery_replay_failed "
                    "telegram_update_id=%s error=%s",
                    message.telegram_update_id,
                    type(exc).__name__,
                )
                mark_failed(
                    message.telegram_update_id,
                    "Startup recovery replay failed",
                )
                failed_replay += 1
                continue

            fail_queued_message(
                message.telegram_update_id,
                "Startup recovery did not claim queued message",
            )

    return StartupQueueDrainSummary(
        replayed=replayed,
        failed_unrecoverable=failed_unrecoverable,
        failed_replay=failed_replay,
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
        .post_init(recover_and_drain_queued_messages)
        .build()
    )

    # Persist supported messages before command or AI handlers do expensive work.
    bot.add_handler(MessageHandler(filters.ALL, record_inbound_update), group=-1)

    for command, handler in COMMAND_HANDLERS:
        bot.add_handler(CommandHandler(command, handler))

    bot.add_handler(
        MessageHandler(
            filters.Document.ALL,
            set_plan,
        )
    )

    bot.add_handler(
        CallbackQueryHandler(
            accept_policy_callback,
            pattern=f"^{POLICY_ACCEPT_CALLBACK}$",
        )
    )
    bot.add_handler(
        CallbackQueryHandler(
            decline_policy_callback,
            pattern=f"^{POLICY_DECLINE_CALLBACK}$",
        )
    )

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
