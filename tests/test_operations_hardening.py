from pathlib import Path

import pytest

from forge_bot.config import Settings, SettingsError


def valid_env() -> dict[str, str]:
    return {
        "TELEGRAM_TOKEN": "telegram-token",
        "DB_HOST": "localhost",
        "DB_USER": "botforge",
        "DB_PASSWORD": "strong-secret",
        "DB_NAME": "botforge",
    }


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_rejects_development_database_password(
    environment: str,
) -> None:
    env = valid_env()
    env["BOTFORGE_ENV"] = environment
    env["DB_PASSWORD"] = "botforge_dev_password"

    with pytest.raises(SettingsError, match="development"):
        Settings.from_env(env)


def test_production_rejects_placeholder_telegram_token() -> None:
    env = valid_env()
    env["BOTFORGE_ENV"] = "production"
    env["TELEGRAM_TOKEN"] = "<telegram_bot_token>"

    with pytest.raises(SettingsError, match="TELEGRAM_TOKEN"):
        Settings.from_env(env)


def test_development_still_allows_documented_defaults() -> None:
    env = valid_env()
    env["DB_PASSWORD"] = "botforge_dev_password"

    settings = Settings.from_env(env)

    assert settings.botforge_env == "development"


def test_backup_and_restore_scripts_are_present() -> None:
    backup_script = Path("scripts/backup_database.sh").read_text(encoding="utf-8")
    restore_script = Path("scripts/restore_database.sh").read_text(encoding="utf-8")

    assert backup_script.startswith("#!/usr/bin/env bash")
    assert restore_script.startswith("#!/usr/bin/env bash")
    assert "pg_dump -Fc" in backup_script
    assert "pg_restore --clean --if-exists --no-owner" in restore_script
    assert 'backup_dir="backups"' in backup_script
    assert 'backup_dir="backups"' in restore_script
    assert "latest_backup" in restore_script
    assert "--force" in restore_script
    assert "--project-name" in backup_script
    assert "--project-name" in restore_script
