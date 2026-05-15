from forge_bot.config import Settings


def make_settings(**overrides: int) -> Settings:
    values = {
        "telegram_token": "token",
        "db_host": "localhost",
        "db_user": "botforge",
        "db_password": "secret",
        "db_name": "botforge",
    } | overrides
    return Settings(**values)
