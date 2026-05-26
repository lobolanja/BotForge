from types import SimpleNamespace
from typing import Any

import pytest

from forge_bot.commands import auth_guard
from forge_bot.commands.privacy import delete_my_data, memory_clear, privacy
from forge_bot.database import MemoryClearResult, UserDeletionResult


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def create_update(user_id: int = 123) -> Any:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        message=FakeMessage(),
    )


def create_context(args: list[str] | None = None) -> Any:
    return SimpleNamespace(args=args or [])


def allow_linked_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)


@pytest.mark.asyncio
async def test_privacy_requires_linked_user(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: False)

    await privacy(update, create_context())

    assert update.message.replies == [auth_guard.INVITE_REQUIRED_MESSAGE]


@pytest.mark.asyncio
async def test_privacy_returns_data_categories_and_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    allow_linked_user(monkeypatch)

    await privacy(update, create_context())

    reply = update.message.replies[0]
    assert "Telegram identity" in reply
    assert "policy acceptance" in reply
    assert "operational message state" in reply
    assert "/memory_clear" in reply
    assert "/delete_my_data" in reply
    assert "database id" not in reply.lower()
    assert "token hash" not in reply.lower()


@pytest.mark.asyncio
async def test_memory_clear_clears_linked_user_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update(user_id=456)
    allow_linked_user(monkeypatch)
    calls: list[int] = []

    def clear_memory_for_telegram_user(telegram_id: int) -> MemoryClearResult:
        calls.append(telegram_id)
        return MemoryClearResult()

    monkeypatch.setattr(
        "forge_bot.commands.privacy.clear_memory_for_telegram_user",
        clear_memory_for_telegram_user,
    )

    await memory_clear(update, create_context())

    assert calls == [456]
    assert update.message.replies == [
        "Memory cleared.\n\nPersonalization memory has been removed for this account."
    ]


@pytest.mark.asyncio
async def test_memory_clear_reports_unlinked_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    allow_linked_user(monkeypatch)
    monkeypatch.setattr(
        "forge_bot.commands.privacy.clear_memory_for_telegram_user",
        lambda telegram_id: None,
    )

    await memory_clear(update, create_context())

    assert update.message.replies == [
        "I could not clear memory because no linked BotForge account was found."
    ]


@pytest.mark.asyncio
async def test_delete_my_data_first_call_creates_request_and_asks_for_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update(user_id=456)
    allow_linked_user(monkeypatch)
    calls: list[int] = []

    def request_user_deletion(telegram_id: int) -> UserDeletionResult:
        calls.append(telegram_id)
        return UserDeletionResult("requested")

    monkeypatch.setattr(
        "forge_bot.commands.privacy.request_user_deletion",
        request_user_deletion,
    )

    await delete_my_data(update, create_context())

    assert calls == [456]
    assert "/delete_my_data CONFIRM" in update.message.replies[0]
    assert "Telegram identity link" in update.message.replies[0]


@pytest.mark.asyncio
async def test_delete_my_data_confirm_deletes_linked_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update(user_id=456)
    allow_linked_user(monkeypatch)
    calls: list[int] = []

    def confirm_user_deletion(telegram_id: int) -> UserDeletionResult:
        calls.append(telegram_id)
        return UserDeletionResult("deleted")

    monkeypatch.setattr(
        "forge_bot.commands.privacy.confirm_user_deletion",
        confirm_user_deletion,
    )

    await delete_my_data(update, create_context(args=["CONFIRM"]))

    assert calls == [456]
    assert update.message.replies == [
        "Data deletion complete.\n\n"
        "Your Telegram identity is no longer linked to BotForge."
    ]


@pytest.mark.asyncio
async def test_delete_my_data_confirm_reports_admin_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    allow_linked_user(monkeypatch)
    monkeypatch.setattr(
        "forge_bot.commands.privacy.confirm_user_deletion",
        lambda telegram_id: UserDeletionResult("manual_review_requested"),
    )

    await delete_my_data(update, create_context(args=["confirm"]))

    assert "administrator access" in update.message.replies[0]


@pytest.mark.asyncio
async def test_delete_my_data_confirm_reports_unlinked_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    allow_linked_user(monkeypatch)
    monkeypatch.setattr(
        "forge_bot.commands.privacy.confirm_user_deletion",
        lambda telegram_id: UserDeletionResult("not_linked"),
    )

    await delete_my_data(update, create_context(args=["CONFIRM"]))

    assert update.message.replies == [
        "I could not delete data because no linked BotForge account was found."
    ]
