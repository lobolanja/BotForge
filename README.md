# BotForge

BotForge is a Docker-first Telegram chatbot stack. The Python bot receives
Telegram messages, checks login state in MariaDB, and sends normal text messages
to a local Ollama model.

The stack runs as separate containers:

- `botforge`: Python Telegram bot process
- `mariadb`: database for users and Telegram login state
- `ollama`: local LLM server
- `ollama-pull`: one-shot container that downloads the configured Ollama model

The bot uses Telegram long polling, so it does not need an inbound public HTTP
port or a webhook URL.

## Runtime Architecture

```text
Telegram user
    |
    v
Telegram Bot API
    |
    v
botforge container
    |-- mariadb container: users, bcrypt passwords, telegram_id login state
    `-- ollama container: local model responses with OLLAMA_MODEL
```

Default internal service endpoints:

- MariaDB: `mariadb:3306`
- Ollama: `http://ollama:11434`
- BotForge: no inbound port; it connects outbound to Telegram with polling

## Requirements

- Docker Engine
- Docker Compose v2, available as `docker compose`
- Telegram bot token from [BotFather](https://t.me/BotFather)
- Enough RAM and disk for the configured Ollama model

## 1. Configure Environment Variables

Create the runtime `.env` file from the template:

```bash
cp .env.example .env
```

Edit `.env` and replace the Telegram token. The other values are generic
development defaults:

```env
TELEGRAM_TOKEN=<telegram_bot_token>

DB_HOST=mariadb
DB_USER=botforge
DB_PASSWORD=botforge_dev_password
DB_NAME=botforge
DB_PORT=3306

MARIADB_ROOT_PASSWORD=botforge_root_password

OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=gemma2:2b
```

Notes:

- Replace `<telegram_bot_token>` with your real token from BotFather and remove
  the angle brackets.
- The database credentials above are development defaults. Change them before
  using this stack outside your local machine.
- `DB_HOST` must be `mariadb` when running inside Docker Compose.
- `OLLAMA_HOST` must be `http://ollama:11434` when running inside Docker Compose.
- `OLLAMA_MODEL` is used by both the `ollama-pull` container and the BotForge
  runtime. The default in this template is `gemma2:2b`, the small Gemma 2 model.
- Do not commit `.env`.

## 2. Build And Start The Stack

```bash
docker compose up -d --build
```

This starts MariaDB, starts Ollama, pulls the configured model, and starts the
BotForge container after the dependencies are healthy.

To use a different Ollama model for this command only, set `OLLAMA_MODEL` before
the Compose command:

```bash
OLLAMA_MODEL=<ollama_model> docker compose up -d --build
```

For a smaller development machine, choose a model that your hardware can run,
for example the default `gemma2:2b` or another small model supported by Ollama.

Check container status:

```bash
docker compose ps
```

Follow BotForge logs:

```bash
docker compose logs -f botforge
```

Expected BotForge log output:

```text
Bot in execution...
```

Check Ollama:

```bash
docker compose exec ollama ollama list
```

Check MariaDB:

```bash
docker compose exec mariadb sh -lc 'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" -e "SHOW TABLES;"'
```

## 3. Create The First Bot User

The MariaDB container creates the `users` table automatically on first startup
from `docker/mariadb/init/001_schema.sh`.

Generate a bcrypt password hash using the BotForge image:

```bash
docker compose run --rm --no-deps botforge python - <<'PY'
import bcrypt

password = b"<bot_user_plain_password>"
print(bcrypt.hashpw(password, bcrypt.gensalt()).decode())
PY
```

Open a MariaDB shell:

```bash
docker compose exec mariadb sh -lc 'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"'
```

Insert the initial user, replacing the hash value:

```sql
INSERT INTO users (username, password)
VALUES ('<bot_user>', '<generated_bcrypt_hash>');
```

Exit MariaDB:

```sql
exit
```

## 4. Telegram Smoke Test

Open a private chat with the bot in Telegram:

```text
/help
/login <bot_user> <bot_user_plain_password>
/status
hello
```

Only one running BotForge container should use the same Telegram token.

## Service Operations

Start the stack:

```bash
docker compose up -d
```

Stop the stack without deleting data:

```bash
docker compose down
```

Restart only the bot:

```bash
docker compose restart botforge
```

Restart Ollama and the bot:

```bash
docker compose restart ollama botforge
```

View logs:

```bash
docker compose logs -f
docker compose logs -f botforge
docker compose logs -f mariadb
docker compose logs -f ollama
```

Rebuild the BotForge image after code changes:

```bash
docker compose up -d --build botforge
```

Pull the Ollama model again:

```bash
docker compose run --rm ollama-pull
```

Pull and switch to a different model:

```bash
OLLAMA_MODEL=<ollama_model> docker compose run --rm ollama-pull
OLLAMA_MODEL=<ollama_model> docker compose up -d --force-recreate botforge
```

Delete all containers and persistent data:

```bash
docker compose down -v
```

Use `docker compose down -v` carefully. It removes the MariaDB and Ollama volumes,
including users and downloaded models.

## Persistent Data

Docker Compose creates named volumes with the Compose project prefix. With the
default project name, these are:

- `botforge_mariadb_data`: MariaDB database files
- `botforge_ollama_data`: downloaded Ollama models

The schema script in `docker/mariadb/init/` is applied only when the MariaDB volume
is created for the first time. If the database volume already exists, update the
schema manually or reset the stack with `docker compose down -v`.

## Local Development

You can use the same Docker stack for development:

```bash
cp .env.example .env
docker compose up -d mariadb ollama ollama-pull
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

For local Python execution outside Docker, change `.env` to reach the exposed or
local services you are using. If you run MariaDB and Ollama only inside Compose,
the current `docker-compose.yml` does not expose their ports to the host.

Run locally:

```bash
python -m forge_bot.main
```

Run checks after installing development dependencies:

```bash
python -m pytest
python -m ruff check .
python -m mypy src
```

## Current Limitations

- `/login` currently receives the username and password inside Telegram chat.
  Use private chats only until the authentication flow is improved.
- The default AI model is `gemma2:2b`, but it can be overridden with
  `OLLAMA_MODEL`.
- The MariaDB schema is initialized with a raw SQL script instead of a migration
  tool.
- The application uses Telegram polling, so it should run as one active bot
  container per Telegram token.

## License

BotForge is licensed under the PolyForm Noncommercial License 1.0.0.

You are free to use, study, and modify the code for personal, educational, or
research purposes. Commercial use requires explicit written permission.

See [LICENSE](LICENSE) for the license text.
