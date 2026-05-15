"""Tests for the /campaign_invite admin command."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from helpers import make_settings

from forge_bot.commands.campaign_invite import (
    campaign_invite,
    parse_campaign_expiration,
)
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
    args: list[str] | None = None,
    bot_username: str | None = "test_bot",
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
def mock_campaign_token() -> InviteToken:
    return InviteToken(
        raw_token="campaign_token_12345",
        token_hash="hashed_campaign_token",
        role="user",
        email=None,
        expires_at=datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
        token_type="campaign",
        max_uses=100,
        invite_link="https://t.me/test_bot?start=campaign_token_12345",
        app_link="tg://resolve?domain=test_bot&start=campaign_token_12345",
    )


def test_parse_campaign_expiration_uses_end_of_utc_day() -> None:
    expires_at = parse_campaign_expiration("2026-06-30")

    assert expires_at == datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_campaign_invite_no_arguments(admin_patches) -> None:
    update = create_update(user_id=123)
    await campaign_invite(update, create_context(args=[]))

    assert "Usage:" in update.message.replies[0]
    assert (
        "/campaign_invite <role> <expires_at> <max_uses>" in update.message.replies[0]
    )


@pytest.mark.asyncio
async def test_campaign_invite_invalid_role_rejected(admin_patches) -> None:
    update = create_update(user_id=123)
    await campaign_invite(
        update,
        create_context(args=["invalid_role", "2026-06-30", "100"]),
    )

    assert "Invalid role" in update.message.replies[0]


@pytest.mark.asyncio
async def test_campaign_invite_professional_role_rejected(admin_patches) -> None:
    update = create_update(user_id=123)
    await campaign_invite(
        update,
        create_context(args=["professional", "2026-06-30", "100"]),
    )

    assert "professional" in update.message.replies[0].lower()
    assert "not available" in update.message.replies[0].lower()


@pytest.mark.asyncio
async def test_campaign_invite_invalid_expiration_rejected(admin_patches) -> None:
    update = create_update(user_id=123)
    await campaign_invite(update, create_context(args=["user", "06-30-2026", "100"]))

    assert "Invalid expiration date" in update.message.replies[0]


@pytest.mark.asyncio
async def test_campaign_invite_invalid_max_uses_rejected(admin_patches) -> None:
    update = create_update(user_id=123)
    await campaign_invite(update, create_context(args=["user", "2026-06-30", "many"]))

    assert "Invalid max uses" in update.message.replies[0]


@pytest.mark.asyncio
async def test_campaign_invite_creation_validation_error(
    admin_patches,
) -> None:
    update = create_update(user_id=123)
    with (
        patch(
            "forge_bot.commands.campaign_invite.get_user_by_telegram_id",
            return_value={"id": 1},
        ),
        patch(
            "forge_bot.commands.campaign_invite.create_campaign_invite_token",
            side_effect=ValueError("Campaign invite max uses must be positive"),
        ),
    ):
        await campaign_invite(update, create_context(args=["user", "2026-06-30", "0"]))

    assert "max uses must be positive" in update.message.replies[0]


@pytest.mark.asyncio
async def test_campaign_invite_user_role_success(
    admin_patches,
    mock_campaign_token: InviteToken,
) -> None:
    update = create_update(user_id=123)
    with (
        patch(
            "forge_bot.commands.campaign_invite.get_user_by_telegram_id",
            return_value={"id": 1},
        ),
        patch(
            "forge_bot.commands.campaign_invite.create_campaign_invite_token",
            return_value=mock_campaign_token,
        ) as create_campaign_invite_token,
    ):
        await campaign_invite(
            update,
            create_context(args=["user", "2026-06-30", "100"]),
        )

    create_campaign_invite_token.assert_called_once()
    response = update.message.replies[0]
    assert "Campaign invite link created" in response
    assert "https://t.me/test_bot?start=" in response
    assert "Role: user" in response
    assert "Max uses: 100" in response


@pytest.mark.asyncio
async def test_campaign_invite_rate_limited_for_admins(
    admin_patches,
    monkeypatch,
) -> None:
    update = create_update(user_id=123)
    limiter = AbuseLimiter(lambda: make_settings(admin_invites_per_hour=1))
    assert limiter.check_admin_invite(user_id=123, chat_id=789).allowed
    monkeypatch.setattr("forge_bot.commands.rate_limit_guard.abuse_limiter", limiter)

    with patch(
        "forge_bot.commands.campaign_invite.get_user_by_telegram_id",
        return_value={"id": 1},
    ):
        await campaign_invite(
            update,
            create_context(args=["user", "2026-06-30", "100"]),
        )

    assert update.message.replies == [ADMIN_INVITE_RATE_LIMIT_MESSAGE]


@pytest.mark.asyncio
async def test_campaign_invite_denies_non_admin() -> None:
    update = create_update(user_id=456)
    with (
        patch("forge_bot.commands.auth_guard.verify_user", return_value=True),
        patch("forge_bot.commands.auth_guard.is_admin", return_value=False),
        patch(
            "forge_bot.commands.auth_guard.has_current_policy_acceptance",
            return_value=True,
        ),
    ):
        await campaign_invite(
            update,
            create_context(args=["user", "2026-06-30", "100"]),
        )

    assert "Admins only" in update.message.replies[0]
