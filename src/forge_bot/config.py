from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from os import environ
from urllib.parse import quote

from dotenv import load_dotenv

DEFAULT_DB_PORT = 5432
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:4b"
DEFAULT_BOT_PROFILE = "default_dev"
DEFAULT_BOT_PROFILES_DIR = "bot_profiles"
DEFAULT_BOT_POLICY_VERSION = "2026-05-08"
DEFAULT_BOT_PRIVACY_NOTICE_VERSION = "2026-05-08"
DEFAULT_INVITE_TOKEN_TTL_HOURS = 24
DEFAULT_CAMPAIGN_INVITE_MAX_USES_LIMIT = 1000
DEFAULT_MESSAGE_PROCESSING_STALE_MINUTES = 30
DEFAULT_MESSAGE_EXPIRATION_HOURS = 24
DEFAULT_MESSAGE_MAX_RETRIES = 1


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
        required = {
            "DB_HOST": _clean(env.get("DB_HOST")),
            "DB_USER": _clean(env.get("DB_USER")),
            "DB_PASSWORD": _clean(env.get("DB_PASSWORD")),
            "DB_NAME": _clean(env.get("DB_NAME")),
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            names = ", ".join(missing)
            raise SettingsError(
                f"Missing required settings: {names}. "
                "Add them to .env or the environment."
            )

        db_port = _parse_db_port(env.get("DB_PORT"))

        return cls(
            db_host=required["DB_HOST"] or "",
            db_user=required["DB_USER"] or "",
            db_password=required["DB_PASSWORD"] or "",
            db_name=required["DB_NAME"] or "",
            db_port=db_port,
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
    analytics_consent_enabled: bool = False
    training_consent_enabled: bool = False

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
        required = {
            "TELEGRAM_TOKEN": _clean(env.get("TELEGRAM_TOKEN")),
            "DB_HOST": _clean(env.get("DB_HOST")),
            "DB_USER": _clean(env.get("DB_USER")),
            "DB_PASSWORD": _clean(env.get("DB_PASSWORD")),
            "DB_NAME": _clean(env.get("DB_NAME")),
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            names = ", ".join(missing)
            raise SettingsError(
                f"Missing required settings: {names}. "
                "Add them to .env or the environment."
            )

        db_port = _parse_db_port(env.get("DB_PORT"))
        return cls(
            telegram_token=required["TELEGRAM_TOKEN"] or "",
            db_host=required["DB_HOST"] or "",
            db_user=required["DB_USER"] or "",
            db_password=required["DB_PASSWORD"] or "",
            db_name=required["DB_NAME"] or "",
            db_port=db_port,
            ollama_host=_clean(env.get("OLLAMA_HOST")) or DEFAULT_OLLAMA_HOST,
            ollama_model=_clean(env.get("OLLAMA_MODEL")) or DEFAULT_OLLAMA_MODEL,
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
            analytics_consent_enabled=_parse_bool(
                env.get("BOT_ANALYTICS_CONSENT_ENABLED")
            ),
            training_consent_enabled=_parse_bool(
                env.get("BOT_TRAINING_CONSENT_ENABLED")
            ),
        )


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
