from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DebugConversationTurn:
    """One user/assistant exchange written only when debug logging is enabled."""

    bot_profile_id: str
    user_message: str
    assistant_message: str
    internal_user_id: int | None = None
    telegram_user_id: int | None = None
    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None
    inbound_message_id: int | None = None
    request_id: str | None = None
    created_at: datetime | None = None


def append_debug_conversation_turn(
    turn: DebugConversationTurn,
    *,
    settings: Settings | None = None,
) -> bool:
    """Append one conversation turn to a per-user text file in debug mode."""
    active_settings = settings or get_settings()
    if not active_settings.debug_conversation_log_enabled:
        return False

    try:
        path = _conversation_log_path(
            directory=Path(active_settings.debug_conversation_log_dir),
            bot_profile_id=turn.bot_profile_id,
            user_key=_user_key(turn),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(_format_turn(turn))
        return True
    except OSError:
        logger.exception(
            "debug_conversation_log_write_failed user_id=%s telegram_user_id=%s "
            "bot_profile_id=%s",
            turn.internal_user_id,
            turn.telegram_user_id,
            turn.bot_profile_id,
        )
        return False


def _conversation_log_path(
    *,
    directory: Path,
    bot_profile_id: str,
    user_key: str,
) -> Path:
    profile_dir = _safe_path_part(bot_profile_id)
    return directory / profile_dir / f"{_safe_path_part(user_key)}.txt"


def _format_turn(turn: DebugConversationTurn) -> str:
    created_at = turn.created_at or datetime.now(timezone.utc)
    timestamp = created_at.astimezone(timezone.utc).isoformat()
    metadata = {
        "at": timestamp,
        "bot_profile_id": turn.bot_profile_id,
        "internal_user_id": turn.internal_user_id,
        "telegram_user_id": turn.telegram_user_id,
        "telegram_chat_id": turn.telegram_chat_id,
        "telegram_message_id": turn.telegram_message_id,
        "inbound_message_id": turn.inbound_message_id,
        "request_id": turn.request_id,
    }
    metadata_lines = "\n".join(
        f"{key}: {value}" for key, value in metadata.items() if value is not None
    )
    return (
        "\n"
        "================================================================================\n"
        f"{metadata_lines}\n\n"
        "[USER]\n"
        f"{turn.user_message.rstrip()}\n\n"
        "[ASSISTANT]\n"
        f"{turn.assistant_message.rstrip()}\n"
    )


def _user_key(turn: DebugConversationTurn) -> str:
    if turn.internal_user_id is not None:
        return f"user_{turn.internal_user_id}"
    if turn.telegram_user_id is not None:
        return f"telegram_{turn.telegram_user_id}"
    return "unknown_user"


def _safe_path_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "unknown"
