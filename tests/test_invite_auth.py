from types import SimpleNamespace
from typing import Any

import pytest

from forge_bot.commands.auth import start, status
from forge_bot.database import InviteRedemption


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


@pytest.mark.asyncio
async def test_start_without_token_shows_invite_identity_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    called = False

    def redeem_invite_token(raw_token: str, telegram_id: int) -> InviteRedemption:
        nonlocal called
        called = True
        return InviteRedemption("success")

    monkeypatch.setattr(
        "forge_bot.commands.auth.redeem_invite_token",
        redeem_invite_token,
    )
    monkeypatch.setattr("forge_bot.commands.auth.status_user", lambda telegram_id: None)

    await start(update, create_context())

    assert not called
    assert update.message.replies == [
        "Welcome to BotForge. Open your invite link to connect your identity."
    ]


@pytest.mark.asyncio
async def test_start_without_token_reports_already_linked_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    monkeypatch.setattr(
        "forge_bot.commands.auth.status_user",
        lambda telegram_id: {"username": "telegram_123_1", "role": "user"},
    )

    await start(update, create_context())

    assert update.message.replies == [
        "Welcome back to BotForge. This Telegram account is already linked."
    ]


@pytest.mark.asyncio
async def test_start_redeems_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update(user_id=456)

    def redeem_invite_token(raw_token: str, telegram_id: int) -> InviteRedemption:
        assert raw_token == "token-123"
        assert telegram_id == 456
        return InviteRedemption(
            "success",
            username="telegram_456_1",
            role="user",
            email="person@example.com",
        )

    monkeypatch.setattr(
        "forge_bot.commands.auth.redeem_invite_token",
        redeem_invite_token,
    )
    monkeypatch.setattr(
        "forge_bot.commands.auth.policy_prompt",
        lambda: "Policy prompt",
    )

    await start(update, create_context(args=["token-123"]))

    assert update.message.replies == [
        "Welcome to BotForge. Open your invite link to connect your identity.",
        "Invite accepted.\n\nPolicy prompt",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redemption_status", "expected_reply"),
    [
        ("invalid", "This invite link is invalid."),
        ("expired", "This invite link has expired."),
        ("used", "This invite link has already been used."),
        ("campaign_full", "This campaign invite link is full."),
        ("db_error", "Invite identity connection is temporarily unavailable."),
    ],
)
async def test_start_reports_token_failures(
    monkeypatch: pytest.MonkeyPatch,
    redemption_status: str,
    expected_reply: str,
) -> None:
    update = create_update()
    monkeypatch.setattr(
        "forge_bot.commands.auth.redeem_invite_token",
        lambda raw_token, telegram_id: InviteRedemption(redemption_status),
    )

    await start(update, create_context(args=["token-123"]))

    assert update.message.replies[-1] == expected_reply


@pytest.mark.asyncio
async def test_start_reports_already_linked_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    monkeypatch.setattr(
        "forge_bot.commands.auth.redeem_invite_token",
        lambda raw_token, telegram_id: InviteRedemption(
            "already_linked",
            username="telegram_123_1",
            email="person@example.com",
        ),
    )

    await start(update, create_context(args=["token-123"]))

    assert update.message.replies[-1] == "This Telegram account is already linked."


@pytest.mark.asyncio
async def test_status_shows_identity_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    monkeypatch.setattr(
        "forge_bot.commands.auth.status_user",
        lambda telegram_id: {
            "username": "telegram_123_1",
            "email": "person@example.com",
            "role": "admin",
        },
    )

    await status(update, create_context())

    assert update.message.replies == [
        "Your Telegram identity is linked to person@example.com with role: admin."
    ]
    assert "logout" not in update.message.replies[0].lower()
    assert "logged in" not in update.message.replies[0].lower()


@pytest.mark.asyncio
async def test_status_handles_campaign_identity_without_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    monkeypatch.setattr(
        "forge_bot.commands.auth.status_user",
        lambda telegram_id: {
            "username": "telegram_123_1",
            "email": None,
            "role": "user",
        },
    )

    await status(update, create_context())

    assert update.message.replies == [
        "Your Telegram identity is linked with role: user."
    ]


@pytest.mark.asyncio
async def test_status_reports_unlinked_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    monkeypatch.setattr("forge_bot.commands.auth.status_user", lambda telegram_id: None)

    await status(update, create_context())

    assert update.message.replies == ["Your Telegram identity is not linked yet."]
