"""Tests for the /invite admin command."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from helpers import make_settings

from forge_bot.commands.invite import invite
from forge_bot.database import InviteToken
from forge_bot.rate_limits import ADMIN_INVITE_RATE_LIMIT_MESSAGE, AbuseLimiter


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def create_update(user_id: int) -> Any:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=789),
        message=FakeMessage(),
    )


def create_context(
    args: list[str] | None = None, bot_username: str | None = "test_bot"
) -> Any:
    return SimpleNamespace(
        args=args or [],
        bot=SimpleNamespace(username=bot_username),
    )


@pytest.fixture
def admin_patches():
    with (
        patch("forge_bot.commands.auth_guard.verify_user", return_value=True),
        patch("forge_bot.commands.auth_guard.is_admin", return_value=True),
        patch(
            "forge_bot.commands.auth_guard.has_current_policy_acceptance",
            return_value=True,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def default_abuse_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "forge_bot.commands.rate_limit_guard.abuse_limiter",
        AbuseLimiter(make_settings),
    )


@pytest.fixture
def mock_token():
    now = datetime.now(timezone.utc)
    return InviteToken(
        raw_token="test_token_12345",
        token_hash="hashed_token",
        role="user",
        email="person@example.com",
        expires_at=now + timedelta(hours=24),
        invite_link="https://t.me/test_bot?start=test_token_12345",
        app_link="tg://resolve?domain=test_bot&start=test_token_12345",
    )


@pytest.mark.asyncio
async def test_invite_no_arguments(admin_patches) -> None:
    update = create_update(user_id=123)
    await invite(update, create_context(args=[]))
    assert "Usage:" in update.message.replies[0]
    assert "/invite <role> <email>" in update.message.replies[0]


@pytest.mark.asyncio
async def test_invite_missing_email(admin_patches) -> None:
    update = create_update(user_id=123)
    await invite(update, create_context(args=["user"]))
    assert "email address is missing" in update.message.replies[0]
    assert "/invite <role> <email>" in update.message.replies[0]


@pytest.mark.asyncio
async def test_invite_too_many_arguments(admin_patches) -> None:
    update = create_update(user_id=123)
    await invite(update, create_context(args=["user", "person@example.com", "extra"]))
    assert "too many arguments" in update.message.replies[0].lower()


@pytest.mark.asyncio
async def test_invite_professional_role_rejected(admin_patches) -> None:
    update = create_update(user_id=123)
    await invite(update, create_context(args=["professional", "person@example.com"]))
    reply = update.message.replies[0].lower()
    assert "professional" in reply
    assert "not available" in reply


@pytest.mark.asyncio
async def test_invite_invalid_role_rejected(admin_patches) -> None:
    update = create_update(user_id=123)
    await invite(update, create_context(args=["invalid_role", "person@example.com"]))
    assert "supported role" in update.message.replies[0]
    assert "invalid_role" in update.message.replies[0]


@pytest.mark.asyncio
async def test_invite_invalid_email_rejected(admin_patches) -> None:
    update = create_update(user_id=123)
    await invite(update, create_context(args=["user", "not-an-email"]))
    assert "email address is invalid" in update.message.replies[0]


@pytest.mark.asyncio
async def test_invite_user_role_success(admin_patches, mock_token) -> None:
    update = create_update(user_id=123)
    with (
        patch(
            "forge_bot.commands.invite.get_user_by_telegram_id", return_value={"id": 1}
        ),
        patch("forge_bot.commands.invite.create_invite_token", return_value=mock_token),
    ):
        await invite(update, create_context(args=["user", "Person@Example.com"]))
    response = update.message.replies[0]
    assert "Invite link created" in response
    assert "https://t.me/test_bot?start=" in response
    assert "Role: user" in response
    assert "Email: person@example.com" in response
    assert "Expires:" in response


@pytest.mark.asyncio
@pytest.mark.parametrize("role_variant", ["USER", "User", "user"])
async def test_invite_case_insensitive_role(
    admin_patches, mock_token, role_variant
) -> None:
    update = create_update(user_id=123)
    with (
        patch(
            "forge_bot.commands.invite.get_user_by_telegram_id", return_value={"id": 1}
        ),
        patch("forge_bot.commands.invite.create_invite_token", return_value=mock_token),
    ):
        await invite(update, create_context(args=[role_variant, "person@example.com"]))
    assert "Invite link created" in update.message.replies[0]


@pytest.mark.asyncio
async def test_invite_no_admin_user_info(admin_patches) -> None:
    update = create_update(user_id=123)
    with patch("forge_bot.commands.invite.get_user_by_telegram_id", return_value=None):
        await invite(update, create_context(args=["user", "person@example.com"]))
    assert "temporarily unavailable" in update.message.replies[0]
    assert "admin details" in update.message.replies[0].lower()


@pytest.mark.asyncio
async def test_invite_no_bot_username(admin_patches) -> None:
    update = create_update(user_id=123)
    with patch(
        "forge_bot.commands.invite.get_user_by_telegram_id", return_value={"id": 1}
    ):
        await invite(
            update,
            create_context(args=["user", "person@example.com"], bot_username=None),
        )
    assert "temporarily unavailable" in update.message.replies[0]
    assert "administrator" in update.message.replies[0].lower()


@pytest.mark.asyncio
async def test_invite_token_creation_failure(admin_patches) -> None:
    update = create_update(user_id=123)
    with (
        patch(
            "forge_bot.commands.invite.get_user_by_telegram_id", return_value={"id": 1}
        ),
        patch("forge_bot.commands.invite.create_invite_token", return_value=None),
    ):
        await invite(update, create_context(args=["user", "person@example.com"]))
    assert "temporarily unavailable" in update.message.replies[0]
    assert "invite creation" in update.message.replies[0].lower()


@pytest.mark.asyncio
async def test_invite_rate_limited_for_admins(admin_patches, monkeypatch) -> None:
    update = create_update(user_id=123)
    limiter = AbuseLimiter(lambda: make_settings(admin_invites_per_hour=1))
    assert limiter.check_admin_invite(user_id=123, chat_id=789).allowed
    monkeypatch.setattr("forge_bot.commands.rate_limit_guard.abuse_limiter", limiter)

    with patch(
        "forge_bot.commands.invite.get_user_by_telegram_id",
        return_value={"id": 1},
    ):
        await invite(update, create_context(args=["user", "person@example.com"]))

    assert update.message.replies == [ADMIN_INVITE_RATE_LIMIT_MESSAGE]


@pytest.mark.asyncio
async def test_invite_denies_non_admin() -> None:
    update = create_update(user_id=456)
    with (
        patch("forge_bot.commands.auth_guard.verify_user", return_value=True),
        patch("forge_bot.commands.auth_guard.is_admin", return_value=False),
        patch(
            "forge_bot.commands.auth_guard.has_current_policy_acceptance",
            return_value=True,
        ),
    ):
        await invite(update, create_context(args=["user", "person@example.com"]))
    assert "Admins only" in update.message.replies[0]
