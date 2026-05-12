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

    assert "/status - Verifica tu identidad vinculada" in update.message.replies[0]
    assert "/invite" not in update.message.replies[0]


@pytest.mark.asyncio
async def test_help_shows_admin_invite_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    update = create_update()
    monkeypatch.setattr("forge_bot.commands.help.is_admin", lambda telegram_id: True)

    await help_command(update, SimpleNamespace())

    assert "/invite <role> <email>" in update.message.replies[0]
    assert (
        "/campaign_invite <role> <expires_at> <max_uses>" in update.message.replies[0]
    )
