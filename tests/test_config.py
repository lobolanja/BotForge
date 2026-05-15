import pytest

from forge_bot.config import (
    DEFAULT_ADMIN_INVITES_PER_HOUR,
    DEFAULT_AI_MAX_RESPONSE_CHARS,
    DEFAULT_AI_TIMEOUT_SECONDS,
    DEFAULT_BOT_POLICY_VERSION,
    DEFAULT_BOT_PRIVACY_NOTICE_VERSION,
    DEFAULT_BOT_PROFILE,
    DEFAULT_BOT_PROFILES_DIR,
    DEFAULT_CAMPAIGN_INVITE_MAX_USES_LIMIT,
    DEFAULT_CHAT_MESSAGES_PER_MINUTE,
    DEFAULT_DB_PORT,
    DEFAULT_GLOBAL_ACTIVE_AI_REQUESTS,
    DEFAULT_GLOBAL_AI_QUEUE_SIZE,
    DEFAULT_LLM_FALLBACK_PROVIDER,
    DEFAULT_LLM_FALLBACK_QUEUE_WAIT_SECONDS,
    DEFAULT_LLM_PRIMARY_PROVIDER,
    DEFAULT_MAX_MESSAGE_CHARS,
    DEFAULT_MESSAGE_EXPIRATION_HOURS,
    DEFAULT_MESSAGE_MAX_RETRIES,
    DEFAULT_MESSAGE_PROCESSING_STALE_MINUTES,
    DEFAULT_NVIDIA_BASE_URL,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_USER_AI_REQUESTS_PER_HOUR,
    DEFAULT_USER_MESSAGES_PER_MINUTE,
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
    assert settings.llm_primary_provider == DEFAULT_LLM_PRIMARY_PROVIDER
    assert settings.llm_fallback_provider == DEFAULT_LLM_FALLBACK_PROVIDER
    assert settings.llm_fallback_queue_wait_seconds == (
        DEFAULT_LLM_FALLBACK_QUEUE_WAIT_SECONDS
    )
    assert settings.nvidia_api_key == ""
    assert settings.nvidia_base_url == DEFAULT_NVIDIA_BASE_URL
    assert settings.nvidia_model == DEFAULT_NVIDIA_MODEL
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
    assert settings.max_message_chars == DEFAULT_MAX_MESSAGE_CHARS
    assert settings.user_messages_per_minute == DEFAULT_USER_MESSAGES_PER_MINUTE
    assert settings.user_ai_requests_per_hour == DEFAULT_USER_AI_REQUESTS_PER_HOUR
    assert settings.chat_messages_per_minute == DEFAULT_CHAT_MESSAGES_PER_MINUTE
    assert settings.global_active_ai_requests == DEFAULT_GLOBAL_ACTIVE_AI_REQUESTS
    assert settings.global_ai_queue_size == DEFAULT_GLOBAL_AI_QUEUE_SIZE
    assert settings.admin_invites_per_hour == DEFAULT_ADMIN_INVITES_PER_HOUR
    assert not settings.analytics_consent_enabled
    assert not settings.training_consent_enabled


def test_abuse_limit_settings_are_configurable() -> None:
    env = valid_env() | {
        "MAX_MESSAGE_CHARS": "2000",
        "USER_MESSAGES_PER_MINUTE": "3",
        "USER_AI_REQUESTS_PER_HOUR": "12",
        "CHAT_MESSAGES_PER_MINUTE": "18",
        "GLOBAL_ACTIVE_AI_REQUESTS": "1",
        "GLOBAL_AI_QUEUE_SIZE": "0",
        "ADMIN_INVITES_PER_HOUR": "4",
    }

    settings = Settings.from_env(env)

    assert settings.max_message_chars == 2000
    assert settings.user_messages_per_minute == 3
    assert settings.user_ai_requests_per_hour == 12
    assert settings.chat_messages_per_minute == 18
    assert settings.global_active_ai_requests == 1
    assert settings.global_ai_queue_size == 0
    assert settings.admin_invites_per_hour == 4


def test_llm_fallback_settings_are_configurable() -> None:
    env = valid_env() | {
        "LLM_PRIMARY_PROVIDER": "OLLAMA",
        "LLM_FALLBACK_PROVIDER": "NVIDIA",
        "LLM_FALLBACK_QUEUE_WAIT_SECONDS": "42",
        "NVIDIA_API_KEY": "secret-key",
        "NVIDIA_BASE_URL": "https://example.test/v1",
        "NVIDIA_MODEL": "nvidia/example-model",
    }

    settings = Settings.from_env(env)

    assert settings.llm_primary_provider == "ollama"
    assert settings.llm_fallback_provider == "nvidia"
    assert settings.llm_fallback_queue_wait_seconds == 42
    assert settings.nvidia_api_key == "secret-key"
    assert settings.nvidia_base_url == "https://example.test/v1"
    assert settings.nvidia_model == "nvidia/example-model"
