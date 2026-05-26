from types import SimpleNamespace
from typing import Any

import pytest

from forge_bot.commands import auth_guard
from forge_bot.commands.help import help_command


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


def allow_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)
    monkeypatch.setattr(
        auth_guard,
        "has_current_policy_acceptance",
        lambda telegram_id: True,
    )


@pytest.mark.asyncio
async def test_help_requires_linked_user(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: False)

    await help_command(update, SimpleNamespace())

    assert update.message.replies == [auth_guard.INVITE_REQUIRED_MESSAGE]


@pytest.mark.asyncio
async def test_help_hides_admin_invite_for_non_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    allow_login(monkeypatch)
    monkeypatch.setattr("forge_bot.commands.help.is_admin", lambda telegram_id: False)

    await help_command(update, SimpleNamespace())

    reply = update.message.replies[0]
    assert "/status - Check your linked identity." in reply
    assert "/privacy - Review stored data and controls." in reply
    assert "/memory_clear - Clear personalization memory." in reply
    assert "/delete_my_data - Start data deletion." in reply
    assert "/set_plan - Upload your nutrition plan JSON files." in reply
    assert "/get_plan - Review or export your active nutrition plan." in reply
    assert "/invite" not in reply


@pytest.mark.asyncio
async def test_help_shows_admin_invite_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    allow_login(monkeypatch)
    monkeypatch.setattr("forge_bot.commands.help.is_admin", lambda telegram_id: True)

    await help_command(update, SimpleNamespace())

    reply = update.message.replies[0]
    assert "/invite <role> <email>" in reply
    assert "/admin_users [limit]" in reply
    assert "/admin_memory <user_id|tg:telegram_id|email:value|username:value>" in reply
    assert "/campaign_invite <role> <expires_at> <max_uses>" in reply
