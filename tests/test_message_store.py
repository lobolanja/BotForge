from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from forge_bot.message_store import normalize_update


class FakeUpdate(SimpleNamespace):
    def to_dict(self) -> dict[str, object]:
        return {"update_id": self.update_id}


def fake_update(message: object) -> FakeUpdate:
    return FakeUpdate(
        update_id=1001,
        message=message,
        effective_chat=SimpleNamespace(id=2002),
        effective_user=SimpleNamespace(id=3003),
    )


def test_normalize_text_message_keeps_queryable_telegram_fields() -> None:
    received_at = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    message = SimpleNamespace(
        message_id=4004,
        date=received_at,
        text="hello bot",
    )

    inbound = normalize_update(fake_update(message))

    assert inbound is not None
    assert inbound.telegram_update_id == 1001
    assert inbound.telegram_message_id == 4004
    assert inbound.chat_id == 2002
    assert inbound.telegram_user_id == 3003
    assert inbound.message_type == "text"
    assert inbound.text == "hello bot"
    assert inbound.received_at == received_at


def test_normalize_file_message_keeps_file_metadata() -> None:
    document = SimpleNamespace(
        file_id="file-id",
        file_unique_id="unique-file-id",
        file_name="report.pdf",
        mime_type="application/pdf",
        file_size=12345,
    )
    message = SimpleNamespace(
        message_id=4005,
        date=datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc),
        text=None,
        document=document,
    )

    inbound = normalize_update(fake_update(message))

    assert inbound is not None
    assert inbound.message_type == "document"
    assert inbound.file_id == "file-id"
    assert inbound.file_unique_id == "unique-file-id"
    assert inbound.file_name == "report.pdf"
    assert inbound.mime_type == "application/pdf"
    assert inbound.file_size == 12345


def test_command_messages_are_not_normalized_as_ai_messages() -> None:
    message = SimpleNamespace(
        message_id=4006,
        date=datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc),
        text="/help",
    )

    assert normalize_update(fake_update(message)) is None


def test_inbound_message_migration_tracks_status_and_file_metadata() -> None:
    migration = Path("migrations/versions/20260513_0006_create_inbound_messages.py")
    contents = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260513_0006"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260512_0005"' in contents
    assert "CREATE TABLE IF NOT EXISTS inbound_messages" in contents
    assert "telegram_update_id BIGINT NOT NULL UNIQUE" in contents
    assert "file_unique_id TEXT NULL" in contents
    assert "retry_count INTEGER NOT NULL DEFAULT 0" in contents
    assert "status IN (" in contents
