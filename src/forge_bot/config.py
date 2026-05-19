from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from os import environ
from urllib.parse import quote

from dotenv import load_dotenv

DEFAULT_DB_PORT = 5432
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:4b"
DEFAULT_LLM_PRIMARY_PROVIDER = "ollama"
DEFAULT_LLM_FALLBACK_PROVIDER = "nvidia"
DEFAULT_LLM_FALLBACK_QUEUE_WAIT_SECONDS = 100
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODEL = "nvidia/llama-3.1-nemotron-nano-8b-v1"
DEFAULT_BOT_PROFILE = "default_dev"
DEFAULT_BOT_PROFILES_DIR = "bot_profiles"
DEFAULT_BOT_POLICY_VERSION = "2026-05-08"
DEFAULT_BOT_PRIVACY_NOTICE_VERSION = "2026-05-08"
DEFAULT_INVITE_TOKEN_TTL_HOURS = 24
DEFAULT_CAMPAIGN_INVITE_MAX_USES_LIMIT = 1000
DEFAULT_MESSAGE_PROCESSING_STALE_MINUTES = 30
DEFAULT_MESSAGE_EXPIRATION_HOURS = 24
DEFAULT_MESSAGE_MAX_RETRIES = 1
DEFAULT_AI_TIMEOUT_SECONDS = 60
DEFAULT_AI_MAX_RESPONSE_CHARS = 4000
DEFAULT_MAX_MESSAGE_CHARS = 4000
DEFAULT_USER_MESSAGES_PER_MINUTE = 6
DEFAULT_USER_AI_REQUESTS_PER_HOUR = 60
DEFAULT_CHAT_MESSAGES_PER_MINUTE = 30
DEFAULT_GLOBAL_ACTIVE_AI_REQUESTS = 2
DEFAULT_GLOBAL_AI_QUEUE_SIZE = 20
DEFAULT_ADMIN_INVITES_PER_HOUR = 50
DEFAULT_MEMORY_RECENT_MESSAGES = 10
DEFAULT_MEMORY_COMPACTION_TRIGGER_MESSAGES = 6
DEFAULT_MEMORY_COMPACTION_SOURCE_MESSAGES = 5
DEFAULT_MEMORY_MAX_MESSAGE_CHARS = 4000
DEFAULT_MEMORY_COMPACTED_MAX_CHARS = 2000
DEFAULT_BOTFORGE_ENV = "development"
PRODUCTION_ENVS = frozenset({"prod", "production"})
DEVELOPMENT_DB_PASSWORD = "botforge_dev_password"
PLACEHOLDER_TELEGRAM_TOKEN = "<telegram_bot_token>"
REQUIRED_DB_SETTINGS = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
REQUIRED_RUNTIME_SETTINGS = ("TELEGRAM_TOKEN", *REQUIRED_DB_SETTINGS)


class SettingsError(RuntimeError):
    """Signal missing or invalid runtime configuration."""


def _clean(value: str | None) -> str | None:
    """Normalize a raw environment variable value.

    Args:
        value: Value read from the environment.

    Returns:
        The stripped value, or None when the value is missing or empty.
    """
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class DatabaseSettings:
    """Validated database settings shared by runtime and migrations.

    Attributes:
        db_host: PostgreSQL host name or address.
        db_user: PostgreSQL user name.
        db_password: PostgreSQL user password.
        db_name: PostgreSQL database name.
        db_port: PostgreSQL port.
    """

    db_host: str
    db_user: str
    db_password: str
    db_name: str
    db_port: int = DEFAULT_DB_PORT

    @classmethod
    def from_env(cls, env: Mapping[str, str] = environ) -> "DatabaseSettings":
        """Build database settings from an environment mapping.

        Args:
            env: Mapping containing environment variable names and values.

        Returns:
            A DatabaseSettings instance with required values and defaults applied.

        Raises:
            SettingsError: If a required setting is missing or DB_PORT is invalid.
        """
        required = _required_clean_values(env, REQUIRED_DB_SETTINGS)

        return cls(
            db_host=required["DB_HOST"],
            db_user=required["DB_USER"],
            db_password=required["DB_PASSWORD"],
            db_name=required["DB_NAME"],
            db_port=_parse_db_port(env.get("DB_PORT")),
        )

    @property
    def database_url(self) -> str:
        """Return the SQLAlchemy-compatible PostgreSQL connection URL.

        Returns:
            A PostgreSQL URL using the psycopg SQLAlchemy driver.
        """
        user = quote(self.db_user, safe="")
        password = quote(self.db_password, safe="")
        host = quote(self.db_host, safe="")
        database = quote(self.db_name, safe="")
        return (
            f"postgresql+psycopg://{user}:{password}@{host}:{self.db_port}/{database}"
        )


@dataclass(frozen=True)
class Settings(DatabaseSettings):
    """Validated runtime settings used by the BotForge application.

    Attributes:
        telegram_token: Token used to connect to the Telegram Bot API.
        db_host: PostgreSQL host name or address.
        db_user: PostgreSQL user name.
        db_password: PostgreSQL user password.
        db_name: PostgreSQL database name.
        db_port: PostgreSQL port.
        ollama_host: Base URL of the Ollama server.
        ollama_model: Model pulled by the Ollama helper container.
        bot_profile: Active bot profile folder name.
        bot_profiles_dir: Directory containing all bot profile folders.
    """

    telegram_token: str = ""
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    llm_primary_provider: str = DEFAULT_LLM_PRIMARY_PROVIDER
    llm_fallback_provider: str = DEFAULT_LLM_FALLBACK_PROVIDER
    llm_fallback_queue_wait_seconds: int = DEFAULT_LLM_FALLBACK_QUEUE_WAIT_SECONDS
    nvidia_api_key: str = ""
    nvidia_base_url: str = DEFAULT_NVIDIA_BASE_URL
    nvidia_model: str = DEFAULT_NVIDIA_MODEL
    bot_profile: str = DEFAULT_BOT_PROFILE
    bot_profiles_dir: str = DEFAULT_BOT_PROFILES_DIR
    bot_policy_version: str = DEFAULT_BOT_POLICY_VERSION
    bot_privacy_notice_version: str = DEFAULT_BOT_PRIVACY_NOTICE_VERSION
    bot_policy_url: str = ""
    invite_token_ttl_hours: int = DEFAULT_INVITE_TOKEN_TTL_HOURS
    campaign_invite_max_uses_limit: int = DEFAULT_CAMPAIGN_INVITE_MAX_USES_LIMIT
    message_processing_stale_minutes: int = DEFAULT_MESSAGE_PROCESSING_STALE_MINUTES
    message_expiration_hours: int = DEFAULT_MESSAGE_EXPIRATION_HOURS
    message_max_retries: int = DEFAULT_MESSAGE_MAX_RETRIES
    ai_timeout_seconds: int = DEFAULT_AI_TIMEOUT_SECONDS
    ai_max_response_chars: int = DEFAULT_AI_MAX_RESPONSE_CHARS
    max_message_chars: int = DEFAULT_MAX_MESSAGE_CHARS
    user_messages_per_minute: int = DEFAULT_USER_MESSAGES_PER_MINUTE
    user_ai_requests_per_hour: int = DEFAULT_USER_AI_REQUESTS_PER_HOUR
    chat_messages_per_minute: int = DEFAULT_CHAT_MESSAGES_PER_MINUTE
    global_active_ai_requests: int = DEFAULT_GLOBAL_ACTIVE_AI_REQUESTS
    global_ai_queue_size: int = DEFAULT_GLOBAL_AI_QUEUE_SIZE
    admin_invites_per_hour: int = DEFAULT_ADMIN_INVITES_PER_HOUR
    memory_enabled: bool = True
    memory_recent_messages: int = DEFAULT_MEMORY_RECENT_MESSAGES
    memory_compaction_trigger_messages: int = (
        DEFAULT_MEMORY_COMPACTION_TRIGGER_MESSAGES
    )
    memory_compaction_source_messages: int = DEFAULT_MEMORY_COMPACTION_SOURCE_MESSAGES
    memory_max_message_chars: int = DEFAULT_MEMORY_MAX_MESSAGE_CHARS
    memory_compacted_max_chars: int = DEFAULT_MEMORY_COMPACTED_MAX_CHARS
    analytics_consent_enabled: bool = False
    training_consent_enabled: bool = False
    botforge_env: str = DEFAULT_BOTFORGE_ENV

    @classmethod
    def from_env(cls, env: Mapping[str, str] = environ) -> "Settings":
        """Build settings from an environment mapping.

        Args:
            env: Mapping containing environment variable names and values.

        Returns:
            A Settings instance with required values and defaults applied.

        Raises:
            SettingsError: If a required setting is missing or DB_PORT is invalid.
        """
        required = _required_clean_values(env, REQUIRED_RUNTIME_SETTINGS)

        db_port = _parse_db_port(env.get("DB_PORT"))
        botforge_env = (_clean(env.get("BOTFORGE_ENV")) or DEFAULT_BOTFORGE_ENV).lower()
        _validate_production_secrets(
            botforge_env,
            telegram_token=required["TELEGRAM_TOKEN"],
            db_password=required["DB_PASSWORD"],
        )

        return cls(
            telegram_token=required["TELEGRAM_TOKEN"],
            db_host=required["DB_HOST"],
            db_user=required["DB_USER"],
            db_password=required["DB_PASSWORD"],
            db_name=required["DB_NAME"],
            db_port=db_port,
            ollama_host=_clean(env.get("OLLAMA_HOST")) or DEFAULT_OLLAMA_HOST,
            ollama_model=_clean(env.get("OLLAMA_MODEL")) or DEFAULT_OLLAMA_MODEL,
            llm_primary_provider=(
                _clean(env.get("LLM_PRIMARY_PROVIDER")) or DEFAULT_LLM_PRIMARY_PROVIDER
            ).lower(),
            llm_fallback_provider=(
                _clean(env.get("LLM_FALLBACK_PROVIDER"))
                or DEFAULT_LLM_FALLBACK_PROVIDER
            ).lower(),
            llm_fallback_queue_wait_seconds=_parse_positive_int(
                env.get("LLM_FALLBACK_QUEUE_WAIT_SECONDS"),
                DEFAULT_LLM_FALLBACK_QUEUE_WAIT_SECONDS,
            ),
            nvidia_api_key=_clean(env.get("NVIDIA_API_KEY")) or "",
            nvidia_base_url=(
                _clean(env.get("NVIDIA_BASE_URL")) or DEFAULT_NVIDIA_BASE_URL
            ),
            nvidia_model=_clean(env.get("NVIDIA_MODEL")) or DEFAULT_NVIDIA_MODEL,
            bot_profile=_clean(env.get("BOT_PROFILE")) or DEFAULT_BOT_PROFILE,
            bot_profiles_dir=(
                _clean(env.get("BOT_PROFILES_DIR")) or DEFAULT_BOT_PROFILES_DIR
            ),
            bot_policy_version=(
                _clean(env.get("BOT_POLICY_VERSION")) or DEFAULT_BOT_POLICY_VERSION
            ),
            bot_privacy_notice_version=(
                _clean(env.get("BOT_PRIVACY_NOTICE_VERSION"))
                or DEFAULT_BOT_PRIVACY_NOTICE_VERSION
            ),
            bot_policy_url=_clean(env.get("BOT_POLICY_URL")) or "",
            invite_token_ttl_hours=_parse_positive_int(
                env.get("INVITE_TOKEN_TTL_HOURS"),
                DEFAULT_INVITE_TOKEN_TTL_HOURS,
            ),
            campaign_invite_max_uses_limit=_parse_positive_int(
                env.get("CAMPAIGN_INVITE_MAX_USES_LIMIT"),
                DEFAULT_CAMPAIGN_INVITE_MAX_USES_LIMIT,
            ),
            message_processing_stale_minutes=_parse_positive_int(
                env.get("MESSAGE_PROCESSING_STALE_MINUTES"),
                DEFAULT_MESSAGE_PROCESSING_STALE_MINUTES,
            ),
            message_expiration_hours=_parse_positive_int(
                env.get("MESSAGE_EXPIRATION_HOURS"),
                DEFAULT_MESSAGE_EXPIRATION_HOURS,
            ),
            message_max_retries=_parse_non_negative_int(
                env.get("MESSAGE_MAX_RETRIES"),
                DEFAULT_MESSAGE_MAX_RETRIES,
            ),
            ai_timeout_seconds=_parse_positive_int(
                env.get("AI_TIMEOUT_SECONDS"),
                DEFAULT_AI_TIMEOUT_SECONDS,
            ),
            ai_max_response_chars=_parse_positive_int(
                env.get("AI_MAX_RESPONSE_CHARS"),
                DEFAULT_AI_MAX_RESPONSE_CHARS,
            ),
            max_message_chars=_parse_positive_int(
                env.get("MAX_MESSAGE_CHARS"),
                DEFAULT_MAX_MESSAGE_CHARS,
            ),
            user_messages_per_minute=_parse_positive_int(
                env.get("USER_MESSAGES_PER_MINUTE"),
                DEFAULT_USER_MESSAGES_PER_MINUTE,
            ),
            user_ai_requests_per_hour=_parse_positive_int(
                env.get("USER_AI_REQUESTS_PER_HOUR"),
                DEFAULT_USER_AI_REQUESTS_PER_HOUR,
            ),
            chat_messages_per_minute=_parse_positive_int(
                env.get("CHAT_MESSAGES_PER_MINUTE"),
                DEFAULT_CHAT_MESSAGES_PER_MINUTE,
            ),
            global_active_ai_requests=_parse_positive_int(
                env.get("GLOBAL_ACTIVE_AI_REQUESTS"),
                DEFAULT_GLOBAL_ACTIVE_AI_REQUESTS,
            ),
            global_ai_queue_size=_parse_non_negative_int(
                env.get("GLOBAL_AI_QUEUE_SIZE"),
                DEFAULT_GLOBAL_AI_QUEUE_SIZE,
            ),
            admin_invites_per_hour=_parse_positive_int(
                env.get("ADMIN_INVITES_PER_HOUR"),
                DEFAULT_ADMIN_INVITES_PER_HOUR,
            ),
            memory_enabled=_parse_bool_default(
                env.get("MEMORY_ENABLED"),
                default=True,
            ),
            memory_recent_messages=_parse_positive_int(
                env.get("MEMORY_RECENT_MESSAGES"),
                DEFAULT_MEMORY_RECENT_MESSAGES,
            ),
            memory_compaction_trigger_messages=_parse_positive_int(
                env.get("MEMORY_COMPACTION_TRIGGER_MESSAGES"),
                DEFAULT_MEMORY_COMPACTION_TRIGGER_MESSAGES,
            ),
            memory_compaction_source_messages=_parse_positive_int(
                env.get("MEMORY_COMPACTION_SOURCE_MESSAGES"),
                DEFAULT_MEMORY_COMPACTION_SOURCE_MESSAGES,
            ),
            memory_max_message_chars=_parse_positive_int(
                env.get("MEMORY_MAX_MESSAGE_CHARS"),
                DEFAULT_MEMORY_MAX_MESSAGE_CHARS,
            ),
            memory_compacted_max_chars=_parse_positive_int(
                env.get("MEMORY_COMPACTED_MAX_CHARS"),
                DEFAULT_MEMORY_COMPACTED_MAX_CHARS,
            ),
            analytics_consent_enabled=_parse_bool(
                env.get("BOT_ANALYTICS_CONSENT_ENABLED")
            ),
            training_consent_enabled=_parse_bool(
                env.get("BOT_TRAINING_CONSENT_ENABLED")
            ),
            botforge_env=botforge_env,
        )


def _required_clean_values(
    env: Mapping[str, str],
    names: tuple[str, ...],
) -> dict[str, str]:
    values = {name: _clean(env.get(name)) for name in names}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        names_text = ", ".join(missing)
        raise SettingsError(
            f"Missing required settings: {names_text}. "
            "Add them to .env or the environment."
        )

    return {name: value for name, value in values.items() if value is not None}


def _parse_db_port(value: str | None) -> int:
    """Parse and validate the DB_PORT setting.

    Args:
        value: Raw DB_PORT value read from the environment.

    Returns:
        The parsed port, or the default port when no value is provided.

    Raises:
        SettingsError: If the value is not an integer or is outside the TCP range.
    """
    cleaned = _clean(value)
    if cleaned is None:
        return DEFAULT_DB_PORT
    try:
        port = int(cleaned)
    except ValueError as exc:
        raise SettingsError("DB_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise SettingsError("DB_PORT must be between 1 and 65535.")
    return port


def _parse_positive_int(value: str | None, default: int) -> int:
    """Parse and validate a positive integer setting.

    Args:
        value: Raw value read from the environment.
        default: Default value when no value is provided.

    Returns:
        The parsed positive integer, or the default.

    Raises:
        SettingsError: If the value is not a positive integer.
    """
    cleaned = _clean(value)
    if cleaned is None:
        return default
    try:
        result = int(cleaned)
    except ValueError as exc:
        raise SettingsError(f"Value must be an integer: {value}") from exc
    if result <= 0:
        raise SettingsError(f"Value must be positive: {value}")
    return result


def _parse_non_negative_int(value: str | None, default: int) -> int:
    """Parse and validate a non-negative integer setting."""
    cleaned = _clean(value)
    if cleaned is None:
        return default
    try:
        result = int(cleaned)
    except ValueError as exc:
        raise SettingsError(f"Value must be an integer: {value}") from exc
    if result < 0:
        raise SettingsError(f"Value must be non-negative: {value}")
    return result


def _parse_bool(value: str | None) -> bool:
    """Parse an optional boolean setting that defaults to false."""
    cleaned = _clean(value)
    if cleaned is None:
        return False
    return cleaned.lower() in {"1", "true", "yes", "on"}


def _parse_bool_default(value: str | None, *, default: bool) -> bool:
    """Parse an optional boolean setting with a caller-provided default."""
    cleaned = _clean(value)
    if cleaned is None:
        return default
    return cleaned.lower() in {"1", "true", "yes", "on"}


def _validate_production_secrets(
    botforge_env: str,
    *,
    telegram_token: str,
    db_password: str,
) -> None:
    """Reject known development placeholders in production mode."""
    if botforge_env not in PRODUCTION_ENVS:
        return

    blocked = []
    if telegram_token == PLACEHOLDER_TELEGRAM_TOKEN:
        blocked.append("TELEGRAM_TOKEN placeholder")
    if db_password == DEVELOPMENT_DB_PASSWORD:
        blocked.append("DB_PASSWORD development default")

    if blocked:
        details = ", ".join(blocked)
        raise SettingsError(
            f"Production configuration cannot use development secrets: {details}."
        )


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Load dotenv values once and return cached database-only settings.

    Returns:
        The validated database settings for the current process.

    Raises:
        SettingsError: If required database configuration is missing or invalid.
    """
    load_dotenv()
    return DatabaseSettings.from_env()


@lru_cache
def get_settings() -> Settings:
    """Load dotenv values once and return cached runtime settings.

    Returns:
        The validated Settings instance for the current process.

    Raises:
        SettingsError: If required configuration is missing or invalid.
    """
    load_dotenv()
    return Settings.from_env()


def validate_settings() -> None:
    """Validate process settings and exit with a clear startup error if needed.

    Raises:
        SystemExit: If the current environment cannot produce valid settings.
    """
    try:
        get_settings()
    except SettingsError as error:
        raise SystemExit(f"Configuration error: {error}") from None


if __name__ == "__main__":
    validate_settings()
