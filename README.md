# BotForge

BotForge is a Docker-first Telegram chatbot stack. The Python bot receives
Telegram messages, checks login state in PostgreSQL, and sends normal text messages
to a local Ollama model.

The stack runs as separate containers:

- `botforge`: Python Telegram bot process
- `postgres`: database for users and Telegram login state
- `ollama`: local LLM server
- `ollama-pull`: one-shot container that downloads the configured Ollama model

The bot uses Telegram long polling, so it does not need an inbound public HTTP
port or a webhook URL.

## Product Roadmap

The beta roadmap is tracked in GitHub issues:

- [Beta readiness issue board](https://github.com/lobolanja/BotForge/issues)
- [Recommended task order](tasks/README.md)
- [Product vision and user stories](tasks/product-vision-user-stories.md)
- [Customer journeys](tasks/customer-journeys.md)

## Runtime Architecture

```text
Telegram user
    |
    v
Telegram Bot API
    |
    v
botforge container
    |-- postgres container: users, bcrypt passwords, telegram_id login state
    `-- ollama container: local model responses with the active profile model
```

Default internal service endpoints:

- PostgreSQL: `postgres:5432`
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

DB_HOST=postgres
DB_USER=botforge
DB_PASSWORD=botforge_dev_password
DB_NAME=botforge
DB_PORT=5432

OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=gemma2:2b

BOT_PROFILE=default_dev
BOT_PROFILES_DIR=bot_profiles
```

Notes:

- Replace `<telegram_bot_token>` with your real token from BotFather and remove
  the angle brackets.
- The database credentials above are development defaults. Change them before
  using this stack outside your local machine.
- `DB_HOST` must be `postgres` when running inside Docker Compose.
- `OLLAMA_HOST` must be `http://ollama:11434` when running inside Docker Compose.
- `OLLAMA_MODEL` is used by the `ollama-pull` container. Keep it aligned with
  the active profile's `llm_model`. The default is `gemma2:2b`, the small
  Gemma 2 model.
- `BOT_PROFILE` selects the active bot-specific behavior. The default
  `default_dev` profile lives in `bot_profiles/default_dev/`.
- `BOT_PROFILES_DIR` points to the directory that contains profile folders.
- Do not commit `.env`.

## Bot Profiles And Prompt Configuration

Bot-specific behavior belongs in `bot_profiles/`, not in Telegram routing,
authentication, database, or runtime infrastructure code. Each profile has its
own folder:

```text
bot_profiles/
  default_dev/
    profile.json
    system_prompt.md
```

`profile.json` defines the assistant identity, model choice, feature flags,
domain rules, disclaimer, and language defaults. Long prompts should live in a
Markdown file referenced by `system_prompt_file`.

Required profile fields:

```text
bot_profile_id
bot_display_name
bot_description
system_prompt or system_prompt_file
domain_rules
disclaimer_text
default_language
llm_provider
llm_model
memory_enabled
analytics_enabled
```

To create a new bot profile:

1. Copy `bot_profiles/default_dev/` to `bot_profiles/<new_profile_id>/`.
2. Update `profile.json`, making sure `bot_profile_id` matches the folder name.
3. Edit `system_prompt.md` with the assistant's role and behavior.
4. Put domain-specific rules in `domain_rules`.
5. Set `llm_model` to the Ollama model the bot should use.
6. Set `BOT_PROFILE=<new_profile_id>` in `.env`.
7. If the model changed, set `OLLAMA_MODEL` to the same value so Compose pulls it.
8. Restart the bot container.

The prompt assembler in `src/forge_bot/prompting.py` builds prompts in a
deterministic order: bot system prompt and rules first, optional memory, recent
conversation messages, then the current user message. Memory inputs are wired as
empty for now because memory implementation is outside the current scope.

## 2. Build And Start The Stack

```bash
docker compose up -d --build
```

This starts PostgreSQL, starts Ollama, pulls the configured model, and starts the
BotForge container after the dependencies are healthy. The BotForge container
runs database migrations before starting the Telegram polling process.

To use a different Ollama model for this command only, set `OLLAMA_MODEL` before
the Compose command:

```bash
OLLAMA_MODEL=<ollama_model> docker compose up -d --build
```

For a smaller development machine, choose a model that your hardware can run,
for example the default `gemma2:2b` or another small model supported by Ollama.

If you previously ran the older MariaDB-based local stack, update your `.env`
from `.env.example` and remove old Compose containers:

```bash
docker compose down --remove-orphans
docker compose up -d --build
```

For a fully clean local database after the engine change, use
`docker compose down -v` instead. That deletes local Docker volumes.

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
Running upgrade  -> 20260505_0001, create users table
Bot in execution...
```

Check Ollama:

```bash
docker compose exec ollama ollama list
```

Check PostgreSQL:

```bash
docker compose exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
```

## 3. Database Migrations

BotForge uses Alembic for versioned database migrations. Docker Compose applies
all pending migrations automatically before starting the bot:

```bash
docker compose up -d --build
```

Run migrations manually when developing outside the BotForge container:

```bash
alembic upgrade head
```

The initial migration creates the `users` table with:

- `id`
- `username`
- `password`
- `telegram_id`
- `created_at`

## 4. Create The First Bot User

Generate a bcrypt password hash using the BotForge image:

```bash
docker compose run --rm --no-deps botforge python - <<'PY'
import bcrypt

password = b"<bot_user_plain_password>"
print(bcrypt.hashpw(password, bcrypt.gensalt()).decode())
PY
```

Open a PostgreSQL shell:

```bash
docker compose exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Insert the initial user, replacing the hash value:

```sql
INSERT INTO users (username, password)
VALUES ('<bot_user>', '<generated_bcrypt_hash>');
```

Exit PostgreSQL:

```sql
\q
```

## 5. Telegram Smoke Test

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
docker compose logs -f postgres
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
```

Then update the active profile's `llm_model` and restart BotForge:

```bash
docker compose up -d --force-recreate botforge
```

Delete all containers and persistent data:

```bash
docker compose down -v
```

Use `docker compose down -v` carefully. It removes the PostgreSQL and Ollama volumes,
including users and downloaded models.

## Persistent Data

Docker Compose creates named volumes with the Compose project prefix. With the
default project name, these are:

- `botforge_postgres_data`: PostgreSQL database files
- `botforge_ollama_data`: downloaded Ollama models

Database schema changes are applied with Alembic migrations. The compatibility
schema script in `docker/postgres/init/` is applied only when the PostgreSQL
volume is created for the first time; Alembic is still the source of truth for
ongoing schema changes.

## Local Development

You can use the same Docker stack for development:

```bash
cp .env.example .env
docker compose up -d postgres ollama ollama-pull
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
alembic upgrade head
```

For local Python execution outside Docker, change `.env` to reach the exposed or
local services you are using. If you run PostgreSQL and Ollama only inside Compose,
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
- The default AI profile uses `gemma2:2b`. Change the active profile's
  `llm_model` to use a different runtime model.
- The application uses Telegram polling, so it should run as one active bot
  container per Telegram token.

## License

BotForge is licensed under the PolyForm Noncommercial License 1.0.0.

You are free to use, study, and modify the code for personal, educational, or
research purposes. Commercial use requires explicit written permission.

See [LICENSE](LICENSE) for the license text.
