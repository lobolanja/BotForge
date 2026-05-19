from types import SimpleNamespace

import pytest

from forge_bot.commands import auth_guard
from forge_bot.commands.policy import (
    POLICY_ACCEPT_CALLBACK,
    POLICY_DECLINE_CALLBACK,
    accept_policy,
    accept_policy_callback,
    decline_policy,
    decline_policy_callback,
    policy,
)


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.reply_calls: list[dict[str, object | None]] = []

    async def reply_text(self, text: str, reply_markup: object | None = None) -> None:
        self.replies.append(text)
        self.reply_calls.append({"text": text, "reply_markup": reply_markup})


class FakeCallbackQuery:
    def __init__(self, message: FakeMessage, data: str) -> None:
        self.message = message
        self.data = data
        self.answers = 0

    async def answer(self) -> None:
        self.answers += 1


def make_update(telegram_id: int = 123) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=telegram_id),
        message=FakeMessage(),
        callback_query=None,
    )


def make_callback_update(
    data: str,
    telegram_id: int = 123,
) -> SimpleNamespace:
    message = FakeMessage()
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=telegram_id),
        message=None,
        callback_query=FakeCallbackQuery(message, data),
    )


@pytest.mark.asyncio
async def test_policy_returns_current_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    update = make_update()
    monkeypatch.setattr(
        "forge_bot.commands.policy.get_settings",
        lambda: SimpleNamespace(bot_policy_url="https://example.test/policy"),
    )
    monkeypatch.setattr(
        "forge_bot.commands.policy.current_policy_versions",
        lambda: SimpleNamespace(
            policy_version="v2",
            privacy_notice_version="privacy-v2",
        ),
    )

    await policy(update, SimpleNamespace())

    assert "Policy version: v2" in update.message.replies[0]
    assert "Privacy notice version: privacy-v2" in update.message.replies[0]
    assert "Full policy: https://example.test/policy" in update.message.replies[0]
    reply_markup = update.message.reply_calls[0]["reply_markup"]
    assert reply_markup is not None
    keyboard = reply_markup.inline_keyboard
    assert keyboard[0][0].text == "Accept policy"
    assert keyboard[0][0].callback_data == POLICY_ACCEPT_CALLBACK
    assert keyboard[0][1].text == "Decline"
    assert keyboard[0][1].callback_data == POLICY_DECLINE_CALLBACK


@pytest.mark.asyncio
async def test_accept_policy_stores_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    update = make_update(telegram_id=456)
    calls: list[int] = []

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.policy.has_current_policy_acceptance",
        lambda user_id: False,
    )
    monkeypatch.setattr(
        "forge_bot.commands.policy.accept_current_policy",
        lambda user_id: calls.append(user_id) or True,
    )

    await accept_policy(update, SimpleNamespace())

    assert calls == [456]
    assert update.message.replies == [
        "Policy accepted.\n\nNext step: You can now send me a message"
    ]


@pytest.mark.asyncio
async def test_decline_policy_keeps_user_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_update()

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.policy.decline_current_policy",
        lambda user_id: True,
    )

    await decline_policy(update, SimpleNamespace())

    assert update.message.replies == [
        (
            "Policy declined.\n\n"
            "What happens next: Protected chat messages will stay unavailable "
            "until you accept the policy\n\n"
            "Available actions:\n"
            "/policy\n"
            "/accept_policy\n"
            "/privacy"
        )
    ]


@pytest.mark.asyncio
async def test_accept_policy_reports_already_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_update()
    called = False

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.policy.has_current_policy_acceptance",
        lambda user_id: True,
    )

    def accept_current_policy(user_id: int) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(
        "forge_bot.commands.policy.accept_current_policy",
        accept_current_policy,
    )

    await accept_policy(update, SimpleNamespace())

    assert not called
    assert update.message.replies == ["You already accepted the current policy."]


@pytest.mark.asyncio
async def test_accept_policy_callback_stores_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_callback_update(POLICY_ACCEPT_CALLBACK, telegram_id=456)
    calls: list[int] = []

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.policy.has_current_policy_acceptance",
        lambda user_id: False,
    )
    monkeypatch.setattr(
        "forge_bot.commands.policy.accept_current_policy",
        lambda user_id: calls.append(user_id) or True,
    )

    await accept_policy_callback(update, SimpleNamespace())

    assert update.callback_query.answers == 1
    assert calls == [456]
    assert update.callback_query.message.replies == [
        "Policy accepted.\n\nNext step: You can now send me a message"
    ]


@pytest.mark.asyncio
async def test_decline_policy_callback_replies_and_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_callback_update(POLICY_DECLINE_CALLBACK)

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.policy.decline_current_policy",
        lambda user_id: True,
    )

    await decline_policy_callback(update, SimpleNamespace())

    assert update.callback_query.answers == 1
    assert update.callback_query.message.replies == [
        (
            "Policy declined.\n\n"
            "What happens next: Protected chat messages will stay unavailable "
            "until you accept the policy\n\n"
            "Available actions:\n"
            "/policy\n"
            "/accept_policy\n"
            "/privacy"
        )
    ]


@pytest.mark.asyncio
async def test_accept_policy_callback_reports_already_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_callback_update(POLICY_ACCEPT_CALLBACK)

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.policy.has_current_policy_acceptance",
        lambda user_id: True,
    )

    await accept_policy_callback(update, SimpleNamespace())

    assert update.callback_query.answers == 1
    assert update.callback_query.message.replies == [
        "You already accepted the current policy."
    ]


@pytest.mark.asyncio
async def test_accept_policy_callback_reports_unlinked_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_callback_update(POLICY_ACCEPT_CALLBACK)

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: False)

    await accept_policy_callback(update, SimpleNamespace())

    assert update.callback_query.answers == 1
    assert update.callback_query.message.replies == [
        "I could not accept the policy because your identity is not linked.\n\n"
        "Available actions:\n"
        "/start"
    ]


@pytest.mark.asyncio
async def test_accept_policy_callback_handles_database_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_callback_update(POLICY_ACCEPT_CALLBACK)

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: None)

    await accept_policy_callback(update, SimpleNamespace())

    assert update.callback_query.answers == 1
    assert update.callback_query.message.replies == [
        "Policy acceptance is temporarily unavailable. Please try again in a moment."
    ]


@pytest.mark.asyncio
async def test_protected_handler_blocks_missing_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_update()
    called = False

    async def protected_handler(update: object, context: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(auth_guard, "verify_user", lambda user_id: True)
    monkeypatch.setattr(
        auth_guard,
        "has_current_policy_acceptance",
        lambda user_id: False,
    )

    await auth_guard.require_login(protected_handler)(update, SimpleNamespace())

    assert not called
    assert update.message.replies == [
        "Please accept the current usage policy before continuing.\n\n"
        "Available actions:\n"
        "/policy\n"
        "/accept_policy\n"
        "/decline_policy"
    ]


@pytest.mark.asyncio
async def test_protected_handler_allows_current_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = make_update()
    called = False

    async def protected_handler(update: object, context: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(auth_guard, "verify_user", lambda user_id: True)
    monkeypatch.setattr(
        auth_guard,
        "has_current_policy_acceptance",
        lambda user_id: True,
    )

    await auth_guard.require_login(protected_handler)(update, SimpleNamespace())

    assert called
    assert update.message.replies == []
