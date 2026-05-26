from types import SimpleNamespace
from typing import Any

import pytest

from forge_bot.commands import admin_memory as admin_memory_module
from forge_bot.commands.admin_memory import admin_memory, admin_users


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def create_update() -> Any:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=FakeMessage(),
    )


def create_context(args: list[str] | None = None) -> Any:
    return SimpleNamespace(args=args or [])


@pytest.fixture(autouse=True)
def admin_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "forge_bot.commands.auth_guard.verify_user",
        lambda user_id: True,
    )
    monkeypatch.setattr("forge_bot.commands.auth_guard.is_admin", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.auth_guard.has_current_policy_acceptance",
        lambda user_id: True,
    )


@pytest.mark.asyncio
async def test_admin_users_lists_identifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    monkeypatch.setattr(
        admin_memory_module,
        "list_admin_users",
        lambda *, limit: [
            {
                "id": 7,
                "telegram_id": 456,
                "role": "user",
                "username": "telegram_456",
                "email": "person@example.com",
            }
        ],
    )

    await admin_users(update, create_context(args=["10"]))

    assert "id=7" in update.message.replies[0]
    assert "tg=456" in update.message.replies[0]
    assert "email=person@example.com" in update.message.replies[0]
    assert "/admin_memory" in update.message.replies[0]


@pytest.mark.asyncio
async def test_admin_memory_returns_report(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    calls: list[tuple[str, str]] = []

    def build_report(identifier: str, *, profile_id: str) -> str:
        calls.append((identifier, profile_id))
        return "User memory\n\nDaily logs: none"

    monkeypatch.setattr(admin_memory_module, "build_admin_memory_report", build_report)

    await admin_memory(update, create_context(args=["7", "nutrition"]))

    assert calls == [("7", "nutrition")]
    assert update.message.replies == ["User memory\n\nDaily logs: none"]


def test_format_memory_report_sections() -> None:
    report = admin_memory_module._format_memory_report(
        user={
            "id": 7,
            "telegram_id": 456,
            "username": "telegram_456",
            "email": None,
            "role": "user",
        },
        profile_id="nutrition",
        snapshot={
            "db_active_plan": None,
            "daily_logs": [
                {
                    "log_date": "2026-05-24",
                    "situation_key": "natacion",
                    "meals": {"desayuno": {"completed": True, "text": "tostada"}},
                    "notes": [],
                }
            ],
            "compact_memory": {
                "summary": "Le gusta cenar pescado.",
                "source_message_count": 12,
                "updated_at": "2026-05-24T10:00:00Z",
            },
            "langchain_messages": [
                {
                    "message": {
                        "type": "human",
                        "data": {"content": "Que ceno?"},
                    }
                }
            ],
            "legacy_messages": [],
        },
    )

    assert "Profile: nutrition" in report
    assert "tipo_dia: natacion" in report
    assert "completed" in report
    assert "Compact memory:" in report
    assert "LangChain recent messages:" in report


def test_resolve_admin_user_rejects_bad_numeric_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        admin_memory_module,
        "conect_db",
        lambda: pytest.fail("database should not be opened"),
    )

    assert admin_memory_module.resolve_admin_user("id:not-a-number") is None
    assert admin_memory_module.resolve_admin_user("tg:not-a-number") is None
