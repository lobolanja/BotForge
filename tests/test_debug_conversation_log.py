from datetime import datetime, timezone

from helpers import make_settings

from forge_bot.debug_conversation_log import (
    DebugConversationTurn,
    append_debug_conversation_turn,
)


def test_debug_conversation_log_is_disabled_by_default(tmp_path) -> None:
    settings = make_settings(debug_conversation_log_dir=str(tmp_path))

    written = append_debug_conversation_turn(
        DebugConversationTurn(
            bot_profile_id="nutrition",
            internal_user_id=7,
            user_message="hola",
            assistant_message="respuesta",
        ),
        settings=settings,
    )

    assert written is False
    assert list(tmp_path.rglob("*.txt")) == []


def test_debug_conversation_log_writes_plain_text_per_user_profile(tmp_path) -> None:
    settings = make_settings(
        debug_conversation_log_enabled=True,
        debug_conversation_log_dir=str(tmp_path),
    )

    written = append_debug_conversation_turn(
        DebugConversationTurn(
            bot_profile_id="nutrition",
            internal_user_id=7,
            telegram_user_id=123,
            telegram_chat_id=456,
            telegram_message_id=99,
            inbound_message_id=55,
            request_id="req-1",
            created_at=datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc),
            user_message="Que ceno?",
            assistant_message="Merluza con verduras.",
        ),
        settings=settings,
    )

    path = tmp_path / "nutrition" / "user_7.txt"
    assert written is True
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "at: 2026-05-24T10:00:00+00:00" in content
    assert "bot_profile_id: nutrition" in content
    assert "internal_user_id: 7" in content
    assert "telegram_user_id: 123" in content
    assert "request_id: req-1" in content
    assert "[USER]\nQue ceno?" in content
    assert "[ASSISTANT]\nMerluza con verduras." in content


def test_debug_conversation_log_sanitizes_path_parts(tmp_path) -> None:
    settings = make_settings(
        debug_conversation_log_enabled=True,
        debug_conversation_log_dir=str(tmp_path),
    )

    written = append_debug_conversation_turn(
        DebugConversationTurn(
            bot_profile_id="../nutrition profile",
            telegram_user_id=123,
            user_message="hola",
            assistant_message="respuesta",
        ),
        settings=settings,
    )

    assert written is True
    assert (tmp_path / "nutrition_profile" / "telegram_123.txt").is_file()
