from types import SimpleNamespace

import pytest

from forge_bot.commands import auth_guard
from forge_bot.commands.policy import accept_policy, decline_policy, policy


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def make_update(telegram_id: int = 123) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=telegram_id),
        message=FakeMessage(),
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


@pytest.mark.asyncio
async def test_accept_policy_stores_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    update = make_update(telegram_id=456)
    calls: list[int] = []

    monkeypatch.setattr("forge_bot.commands.policy.verify_user", lambda user_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.policy.accept_current_policy",
        lambda user_id: calls.append(user_id) or True,
    )

    await accept_policy(update, SimpleNamespace())

    assert calls == [456]
    assert update.message.replies == ["Policy accepted. You can now use BotForge."]


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
        "Policy declined. BotForge cannot be used until you accept /policy."
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
        "Please accept the current usage policy before using BotForge. "
        "Use /policy and then /accept_policy."
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
