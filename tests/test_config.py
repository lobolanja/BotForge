import pytest

from forge_bot.config import (
    DEFAULT_AI_MAX_RESPONSE_CHARS,
    DEFAULT_AI_TIMEOUT_SECONDS,
    DEFAULT_BOT_POLICY_VERSION,
    DEFAULT_BOT_PRIVACY_NOTICE_VERSION,
    DEFAULT_BOT_PROFILE,
    DEFAULT_BOT_PROFILES_DIR,
    DEFAULT_CAMPAIGN_INVITE_MAX_USES_LIMIT,
    DEFAULT_DB_PORT,
    DEFAULT_MESSAGE_EXPIRATION_HOURS,
    DEFAULT_MESSAGE_MAX_RETRIES,
    DEFAULT_MESSAGE_PROCESSING_STALE_MINUTES,
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
    assert settings.bot_policy_version == DEFAULT_BOT_POLICY_VERSION
    assert settings.bot_privacy_notice_version == DEFAULT_BOT_PRIVACY_NOTICE_VERSION
    assert settings.campaign_invite_max_uses_limit == (
        DEFAULT_CAMPAIGN_INVITE_MAX_USES_LIMIT
    )
    assert settings.message_processing_stale_minutes == (
        DEFAULT_MESSAGE_PROCESSING_STALE_MINUTES
    )
    assert settings.message_expiration_hours == DEFAULT_MESSAGE_EXPIRATION_HOURS
    assert settings.message_max_retries == DEFAULT_MESSAGE_MAX_RETRIES
    assert settings.ai_timeout_seconds == DEFAULT_AI_TIMEOUT_SECONDS
    assert settings.ai_max_response_chars == DEFAULT_AI_MAX_RESPONSE_CHARS
    assert not settings.analytics_consent_enabled
    assert not settings.training_consent_enabled
