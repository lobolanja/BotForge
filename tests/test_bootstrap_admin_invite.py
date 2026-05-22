from datetime import datetime, timezone
from typing import Any

from forge_bot import bootstrap_admin_invite
from forge_bot.database import InviteToken


class FakeCursor:
    def __init__(self, fetchone_result: dict[str, Any] | None) -> None:
        self.fetchone_result = fetchone_result
        self.statements: list[str] = []
        self.params: list[tuple[Any, ...] | None] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        params: tuple[Any, ...] | None = None,
    ) -> None:
        self.statements.append(" ".join(statement.split()))
        self.params.append(params)

    def fetchone(self) -> dict[str, Any] | None:
        return self.fetchone_result


class FakeConnection:
    def __init__(self, fetchone_result: dict[str, Any] | None) -> None:
        self.cursor_obj = FakeCursor(fetchone_result)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


def test_bootstrap_admin_invite_from_env_skips_without_email(monkeypatch) -> None:
    create_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "forge_bot.bootstrap_admin_invite.database.create_invite_token",
        lambda **kwargs: create_calls.append(kwargs),
    )

    result = bootstrap_admin_invite.bootstrap_admin_invite_from_env({})

    assert result.status == "skipped"
    assert "BOOTSTRAP_ADMIN_EMAIL" in str(result.reason)
    assert create_calls == []


def test_bootstrap_admin_invite_skips_when_admin_exists(monkeypatch) -> None:
    connection = FakeConnection({"id": 1})
    monkeypatch.setattr(
        "forge_bot.bootstrap_admin_invite.database.conect_db",
        lambda: connection,
    )

    result = bootstrap_admin_invite.bootstrap_admin_invite(
        email="owner@example.com",
        bot_username="test_bot",
    )

    assert result.status == "skipped"
    assert result.reason == "an active admin user already exists"
    assert connection.closed is True


def test_bootstrap_admin_invite_skips_when_pending_invite_exists(monkeypatch) -> None:
    connections = iter([FakeConnection(None), FakeConnection({"id": 2})])
    monkeypatch.setattr(
        "forge_bot.bootstrap_admin_invite.database.conect_db",
        lambda: next(connections),
    )

    result = bootstrap_admin_invite.bootstrap_admin_invite(
        email="owner@example.com",
        bot_username="test_bot",
    )

    assert result.status == "skipped"
    assert "unused admin invite already exists" in str(result.reason)


def test_bootstrap_admin_invite_creates_admin_invite(monkeypatch) -> None:
    connections = iter([FakeConnection(None), FakeConnection(None)])
    create_calls: list[dict[str, Any]] = []

    def create_invite_token(**kwargs: Any) -> InviteToken:
        create_calls.append(kwargs)
        return InviteToken(
            raw_token="raw",
            token_hash="hash",
            role="admin",
            email=kwargs["email"],
            expires_at=datetime.now(timezone.utc),
            invite_link="https://t.me/test_bot?start=raw",
            app_link="tg://resolve?domain=test_bot&start=raw",
        )

    monkeypatch.setattr(
        "forge_bot.bootstrap_admin_invite.database.conect_db",
        lambda: next(connections),
    )
    monkeypatch.setattr(
        "forge_bot.bootstrap_admin_invite.database.create_invite_token",
        create_invite_token,
    )

    result = bootstrap_admin_invite.bootstrap_admin_invite(
        email="owner@example.com",
        bot_username="test_bot",
        ttl_hours=24,
    )

    assert result.status == "created"
    assert result.invite_link == "https://t.me/test_bot?start=raw"
    assert create_calls == [
        {
            "role": "admin",
            "email": "owner@example.com",
            "ttl_hours": 24,
            "bot_username": "test_bot",
        }
    ]
