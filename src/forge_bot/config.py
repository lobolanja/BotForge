from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from os import environ
from urllib.parse import quote

from dotenv import load_dotenv


DEFAULT_DB_PORT = 5432
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma2:2b"


class SettingsError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    db_host: str
    db_user: str
    db_password: str
    db_name: str
    db_port: int = DEFAULT_DB_PORT
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str = DEFAULT_OLLAMA_MODEL

    @classmethod
    def from_env(cls, env: Mapping[str, str] = environ) -> "Settings":
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
                f"Missing required settings: {names}. Add them to .env or the environment."
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
        )

    @property
    def database_url(self) -> str:
        user = quote(self.db_user, safe="")
        password = quote(self.db_password, safe="")
        host = quote(self.db_host, safe="")
        database = quote(self.db_name, safe="")
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{host}:{self.db_port}/{database}"
        )


def _parse_db_port(value: str | None) -> int:
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


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    return Settings.from_env()


def validate_settings() -> None:
    try:
        get_settings()
    except SettingsError as error:
        raise SystemExit(f"Configuration error: {error}") from None


if __name__ == "__main__":
    validate_settings()
