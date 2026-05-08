from types import SimpleNamespace

from forge_bot.commands.auth import login_disabled, start
from forge_bot.database import (
    InviteRedemption,
    build_invite_link,
    build_telegram_app_link,
    generate_invite_token,
    hash_invite_token,
)


class ReplyRecorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.messages.append(text)


def make_update(telegram_id: int = 123) -> SimpleNamespace:
    return SimpleNamespace(
        message=ReplyRecorder(),
        effective_user=SimpleNamespace(id=telegram_id),
    )


def test_invite_token_hash_does_not_store_raw_token() -> None:
    raw_token = generate_invite_token()
    token_hash = hash_invite_token(raw_token)

    assert raw_token
    assert token_hash != raw_token
    assert len(token_hash) == 64
    assert hash_invite_token(raw_token) == token_hash


def test_build_invite_link_uses_telegram_deep_link() -> None:
    link = build_invite_link("@example_bot", "raw-token")

    assert link == "https://t.me/example_bot?start=raw-token"


def test_build_telegram_app_link_bypasses_preview_page() -> None:
    link = build_telegram_app_link("@example_bot", "raw-token")

    assert link == "tg://resolve?domain=example_bot&start=raw-token"


async def test_start_without_token_returns_invite_prompt() -> None:
    update = make_update()

    await start(update, SimpleNamespace(args=[]))

    assert update.message.messages == [
        "Welcome to BotForge. Open your invite link to authenticate."
    ]


async def test_start_redeems_valid_invite(monkeypatch) -> None:
    update = make_update(telegram_id=456)
    calls: list[tuple[str, int]] = []

    def fake_redeem(raw_token: str, telegram_id: int) -> InviteRedemption:
        calls.append((raw_token, telegram_id))
        return InviteRedemption("success", username="telegram_456", role="user")

    monkeypatch.setattr("forge_bot.commands.auth.redeem_invite_token", fake_redeem)

    await start(update, SimpleNamespace(args=["raw-token"]))

    assert calls == [("raw-token", 456)]
    assert update.message.messages == [
        "Invite accepted. You can now chat with BotForge."
    ]


async def test_start_reports_used_invite(monkeypatch) -> None:
    update = make_update()

    def fake_redeem(raw_token: str, telegram_id: int) -> InviteRedemption:
        return InviteRedemption("used")

    monkeypatch.setattr("forge_bot.commands.auth.redeem_invite_token", fake_redeem)

    await start(update, SimpleNamespace(args=["raw-token"]))

    assert update.message.messages == ["This invite link has already been used."]


async def test_login_disabled_points_to_invite_auth() -> None:
    update = make_update()

    await login_disabled(update, SimpleNamespace(args=[]))

    assert update.message.messages == [
        "Password login is disabled. Open your Telegram invite link to authenticate."
    ]
