from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge_bot.database import create_campaign_invite_token


def test_campaign_redemption_uses_row_lock_and_guarded_counter_update() -> None:
    contents = Path("src/forge_bot/database.py").read_text(encoding="utf-8")

    assert "FROM invite_tokens\n                FOR UPDATE" in contents
    assert "used_count < max_uses" in contents
    assert "SET used_count = used_count + 1" in contents
    assert "INSERT INTO invite_token_redemptions" in contents


def test_create_campaign_invite_rejects_max_uses_above_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "forge_bot.database.get_settings",
        lambda: SimpleNamespace(campaign_invite_max_uses_limit=10),
    )

    with pytest.raises(ValueError, match="exceeds 10"):
        create_campaign_invite_token(
            role="user",
            expires_at=datetime(2026, 6, 30),
            max_uses=11,
        )
