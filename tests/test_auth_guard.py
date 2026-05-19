from types import SimpleNamespace

import pytest

from forge_bot.commands import auth_guard


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


@pytest.mark.asyncio
async def test_admin_required_denies_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=message,
    )
    context = SimpleNamespace()
    called = False

    async def protected_handler(update: object, context: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)
    monkeypatch.setattr(auth_guard, "is_admin", lambda telegram_id: False)

    wrapped = auth_guard.admin_required(protected_handler)
    await wrapped(update, context)

    assert not called
    assert message.replies == [auth_guard.ADMINS_ONLY_MESSAGE]
