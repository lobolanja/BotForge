FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY bot_profiles ./bot_profiles
COPY alembic.ini ./
COPY migrations ./migrations

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN useradd --system --create-home --home-dir /home/botforge botforge
USER botforge

CMD ["sh", "-c", "python -c 'from forge_bot.config import validate_settings; validate_settings()' && alembic upgrade head && python -m forge_bot.bootstrap_admin_invite && python -m forge_bot.main"]
