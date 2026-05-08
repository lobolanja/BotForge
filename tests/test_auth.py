from types import SimpleNamespace

import pytest

from forge_bot.commands import auth


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


@pytest.mark.asyncio
async def test_login_requires_logout_before_switching_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=message,
    )
    context = SimpleNamespace(args=["other-user", "password"])

    def fail_login_user(username: str, password: str, telegram_id: int) -> bool:
        raise AssertionError("login_user should not be called")

    monkeypatch.setattr(auth, "status_user", lambda telegram_id: {"username": "alex"})
    monkeypatch.setattr(auth, "login_user", fail_login_user)

    await auth.login(update, context)

    assert message.replies == [
        "You are already logged in as alex. Use /logout before logging in with "
        "another account."
    ]
