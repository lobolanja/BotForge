import pytest

from forge_bot.config import (
    DEFAULT_BOT_PROFILE,
    DEFAULT_BOT_PROFILES_DIR,
    DEFAULT_DB_PORT,
    DEFAULT_ENABLE_LEGACY_LOGIN,
    DEFAULT_OLLAMA_MODEL,
    DatabaseSettings,
    Settings,
    SettingsError,
)


def valid_env() -> dict[str, str]:
    return {
        "TELEGRAM_TOKEN": "telegram-token",
        "DB_HOST": "localhost",
        "DB_USER": "botforge",
        "DB_PASSWORD": "secret",
        "DB_NAME": "botforge",
    }


def test_missing_telegram_token_fails_fast() -> None:
    env = valid_env()
    del env["TELEGRAM_TOKEN"]

    with pytest.raises(SettingsError, match="TELEGRAM_TOKEN"):
        Settings.from_env(env)


def test_missing_db_password_fails_fast() -> None:
    env = valid_env()
    del env["DB_PASSWORD"]

    with pytest.raises(SettingsError, match="DB_PASSWORD"):
        Settings.from_env(env)


def test_database_settings_do_not_require_telegram_token() -> None:
    env = valid_env()
    del env["TELEGRAM_TOKEN"]

    settings = DatabaseSettings.from_env(env)

    assert settings.db_host == "localhost"


def test_defaults_are_applied() -> None:
    settings = Settings.from_env(valid_env())

    assert settings.db_port == DEFAULT_DB_PORT
    assert settings.ollama_model == DEFAULT_OLLAMA_MODEL
    assert settings.bot_profile == DEFAULT_BOT_PROFILE
    assert settings.bot_profiles_dir == DEFAULT_BOT_PROFILES_DIR
