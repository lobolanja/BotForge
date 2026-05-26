from types import SimpleNamespace
from typing import Any

import pytest

from forge_bot.commands import auth_guard
from forge_bot.commands.auth import start, status
from forge_bot.database import InviteRedemption


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.reply_calls: list[dict[str, object | None]] = []

    async def reply_text(self, text: str, reply_markup: object | None = None) -> None:
        self.replies.append(text)
        self.reply_calls.append({"text": text, "reply_markup": reply_markup})


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
        "Welcome to BotForge.\n\n"
        "Next step: Open your invite link to connect your identity"
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
        "Welcome back to BotForge.\n\nStatus: This Telegram account is already linked"
    ]


@pytest.mark.asyncio
async def test_start_redeems_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update(user_id=456)
    reply_markup = object()

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
    monkeypatch.setattr(
        "forge_bot.commands.auth.policy_action_keyboard",
        lambda: reply_markup,
    )

    await start(update, create_context(args=["token-123"]))

    assert update.message.replies == [
        "Welcome to BotForge.\n\n"
        "Next step: Open your invite link to connect your identity",
        "Invite accepted.\n\nPolicy prompt",
    ]
    assert update.message.reply_calls[-1]["reply_markup"] is reply_markup


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redemption_status", "expected_reply"),
    [
        ("invalid", "I could not accept that invite because it is invalid."),
        ("expired", "I could not accept that invite because it has expired."),
        ("used", "I could not accept that invite because it has already been used."),
        (
            "campaign_full",
            "I could not accept that invite because it has reached its use limit.",
        ),
        (
            "db_error",
            "Invite redemption is temporarily unavailable. "
            "Please try again in a moment.",
        ),
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

    assert update.message.replies[-1] == (
        "This Telegram account is already linked.\n\nAvailable actions:\n/status"
    )


@pytest.mark.asyncio
async def test_status_shows_identity_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)
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
        "Identity linked.\n\nEmail: person@example.com\nRole: admin"
    ]
    assert "logout" not in update.message.replies[0].lower()
    assert "logged in" not in update.message.replies[0].lower()


@pytest.mark.asyncio
async def test_status_handles_campaign_identity_without_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)
    monkeypatch.setattr(
        "forge_bot.commands.auth.status_user",
        lambda telegram_id: {
            "username": "telegram_123_1",
            "email": None,
            "role": "user",
        },
    )

    await status(update, create_context())

    assert update.message.replies == ["Identity linked.\n\nRole: user"]


@pytest.mark.asyncio
async def test_status_denies_unlinked_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: False)

    await status(update, create_context())

    assert update.message.replies == [auth_guard.INVITE_REQUIRED_MESSAGE]
