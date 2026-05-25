from types import SimpleNamespace
from typing import Any

import pytest

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


@pytest.mark.asyncio
async def test_help_hides_admin_invite_for_non_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = create_update()
    monkeypatch.setattr("forge_bot.commands.help.is_admin", lambda telegram_id: False)

    await help_command(update, SimpleNamespace())

    assert "/status - Check your linked identity." in update.message.replies[0]
    assert "/privacy - Review stored data and controls." in update.message.replies[0]
    assert "/memory_clear - Clear personalization memory." in update.message.replies[0]
    assert "/delete_my_data - Start data deletion." in update.message.replies[0]
    assert (
        "/set_plan - Upload your nutrition plan JSON files."
        in (update.message.replies[0])
    )
    assert (
        "/get_plan - Review or export your active nutrition plan."
        in (update.message.replies[0])
    )
    assert "/invite" not in update.message.replies[0]


@pytest.mark.asyncio
async def test_help_shows_admin_invite_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    monkeypatch.setattr("forge_bot.commands.help.is_admin", lambda telegram_id: True)

    await help_command(update, SimpleNamespace())

    assert "/invite <role> <email>" in update.message.replies[0]
    assert "/admin_users [limit]" in update.message.replies[0]
    assert (
        "/admin_memory <user_id|tg:telegram_id|email:value|username:value>"
        in (update.message.replies[0])
    )
    assert (
        "/campaign_invite <role> <expires_at> <max_uses>" in update.message.replies[0]
    )
