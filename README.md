# BotForge

BotForge is a Docker-first Telegram chatbot stack. The Python bot receives
Telegram messages, checks invite-linked identity state in PostgreSQL, and sends
normal text messages to a local Ollama model.

The stack runs as separate containers:

- `botforge`: Python Telegram bot process
- `postgres`: database for users, invite tokens, and policy acceptance
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
- [Beta release checklist](docs/beta-release-checklist.md)
- [Privacy and retention inventory](docs/privacy-and-retention.md)

## Runtime Architecture

```text
Telegram user
    |
    v
Telegram Bot API
    |
    v
botforge container
    |-- postgres container: users, invite tokens, policy acceptance
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

BOTFORGE_ENV=development

DB_HOST=postgres
DB_USER=botforge
DB_PASSWORD=botforge_dev_password
DB_NAME=botforge
DB_PORT=5432

OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=gemma3:4b

LLM_PRIMARY_PROVIDER=profile
LLM_FALLBACK_PROVIDER=nvidia
LLM_FALLBACK_QUEUE_WAIT_SECONDS=100
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5

BOT_PROFILE=default_dev
BOT_PROFILES_DIR=bot_profiles

BOOTSTRAP_ADMIN_EMAIL=
BOOTSTRAP_BOT_USERNAME=
BOOTSTRAP_ADMIN_INVITE_TTL_HOURS=24
BOOTSTRAP_ADMIN_INVITE_FORCE=false
```

Notes:

- Replace `<telegram_bot_token>` with your real token from BotFather and remove
  the angle brackets.
- Keep `BOTFORGE_ENV=development` for local work. Set `BOTFORGE_ENV=production`
  for beta or production deployments; startup fails if the Telegram token is
  still the placeholder or `DB_PASSWORD` is still `botforge_dev_password`.
- The database credentials above are development defaults. Change them before
  using this stack outside your local machine.
- `DB_HOST` must be `postgres` when running inside Docker Compose.
- `OLLAMA_HOST` must be `http://ollama:11434` when running inside Docker Compose.
- `OLLAMA_MODEL` is used only by the `ollama-pull` container. Keep it aligned
  with the active profile's `llm_model` only when that profile uses Ollama.
  The default is `gemma3:4b`, a balanced Gemma model for local development on
  machines with limited RAM.
- `LLM_PRIMARY_PROVIDER=profile` lets each bot profile select its own provider.
  Set it to `ollama` or `nvidia` only when you want to force one provider for
  every profile. `LLM_FALLBACK_PROVIDER=nvidia` enables fallback through NVIDIA
  NIM when the primary provider errors or when the lifecycle queue wait exceeds
  `LLM_FALLBACK_QUEUE_WAIT_SECONDS`.
- `NVIDIA_BASE_URL` defaults to NVIDIA's OpenAI-compatible hosted NIM endpoint,
  `https://integrate.api.nvidia.com/v1`. Choose `NVIDIA_MODEL` from the current
  NVIDIA API Catalog and set `NVIDIA_API_KEY` only in local or deployment
  secrets, never in git.
- `BOT_PROFILE` selects the active bot-specific behavior. The default
  `default_dev` profile lives in `bot_profiles/default_dev/`.
- `BOT_PROFILES_DIR` points to the directory that contains profile folders.
- `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_BOT_USERNAME` optionally create the
  first admin invite during Docker startup, after migrations run. Leave them
  blank to disable the bootstrap. If an admin user already exists, no invite is
  created.
- `BOOTSTRAP_ADMIN_INVITE_FORCE=true` creates a fresh admin invite even when an
  unused admin invite for the same email already exists.
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
  nutrition/
    profile.json
    system_prompt.md
    demo_plan.json
    docs/
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
5. Set `llm_provider` and `llm_model` to the provider/model the bot should use.
6. Set `BOT_PROFILE=<new_profile_id>` in `.env`.
7. If the profile uses Ollama and the model changed, set `OLLAMA_MODEL` to the
   same value so Compose pulls it.
8. Restart the bot container.

The built-in nutrition profile can be enabled with:

```env
BOT_PROFILE=nutrition
```

Its product notes, user journeys, data contracts, and roadmap live under
`bot_profiles/nutrition/docs/`. The first version is intentionally conservative:
it helps interpret a plan provided by the user, asks for missing context before
giving quantities, and avoids inventing diets, medical advice, macros, or JSON
details unless the user explicitly asks.

For local validation before user-level persistence exists, the nutrition profile
also loads `bot_profiles/nutrition/demo_plan.json` as read-only profile context.
That demo plan includes `situaciones` plus `comidas`, so the bot can answer
questions such as "hoy tengo crossfit, que como al mediodia?" by resolving the
day situation and meal moment to the matching food block.

The prompt assembler in `src/forge_bot/prompting.py` builds prompts in a
deterministic order: bot system prompt and rules first, optional memory, recent
conversation messages, then the current user message.

When memory is enabled globally and in the active bot profile, BotForge stores a
bounded recent window per internal user and bot profile. The default window keeps
the last 10 user/assistant messages. After 6 unsummarized messages are present,
the bot asks the configured LLM to compact the oldest 5 into a durable summary
of important dates, tastes, preferences, priorities, goals, and constraints. The
process keeps a per-user/profile cache in memory after the first database load,
so normal follow-up prompts do not reread the same context from PostgreSQL.

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
for example the default `gemma3:4b` or another model supported by Ollama.

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

The `botforge`, `postgres`, and `ollama` services include Docker health checks.
`botforge` validates configuration without printing secret values.

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

Later migrations add invite-token identity linking:

- `users.role`
- `invite_tokens.token_hash` stores a bcrypt hash, not the raw token
- `invite_tokens.role`
- `invite_tokens.expires_at`
- `invite_tokens.used_at`
- `invite_tokens.used_by_user_id`
- `invite_tokens.created_by_user_id`
- `inbound_messages` stores supported Telegram message metadata and processing
  state before AI work starts

## 4. Inbound Message Recovery

BotForge uses Telegram long polling. Telegram may keep pending bot updates while
the bot is offline, but only for up to 24 hours. BotForge cannot retrieve
arbitrary old chat history through the normal Bot API, so messages that Telegram
never delivers during that retention window are unrecoverable.

Supported incoming non-command text and file messages are persisted in
`inbound_messages` before AI processing starts. The table tracks the Telegram
`update_id`, `message_id`, chat and user ids, message type, optional text, file
metadata, retry count, and a durable status:

```text
persisted -> queued -> processing -> answered
persisted -> ignored
processing -> failed
processing -> queued
queued/processing -> expired
```

On startup, BotForge scans unfinished rows. Messages older than
`MESSAGE_EXPIRATION_HOURS` are marked `expired`. Stale `processing` rows older
than `MESSAGE_PROCESSING_STALE_MINUTES` are moved back to `queued` until
`MESSAGE_MAX_RETRIES` is exceeded, then they are marked `failed`.

File messages store Telegram file metadata such as `file_id`, `file_unique_id`,
file name, MIME type, and size. If a file must be preserved long term, download
and archive it soon after receipt; a known `file_id` can request a fresh
Telegram download path later, subject to Telegram Bot API file limits.

## 5. Abuse Prevention And Rate Limits

BotForge applies conservative in-memory limits before expensive AI work starts.
These limits are meant for beta safety and reset when the bot process restarts:

```env
MAX_MESSAGE_CHARS=4000
USER_MESSAGES_PER_MINUTE=6
USER_AI_REQUESTS_PER_HOUR=60
CHAT_MESSAGES_PER_MINUTE=30
GLOBAL_ACTIVE_AI_REQUESTS=2
GLOBAL_AI_QUEUE_SIZE=20
ADMIN_INVITES_PER_HOUR=50
```

When a limit is exceeded, users receive a short friendly message. The bot logs
the limit name, user id, chat id, timestamp, and small counters only; it does
not include raw private message text in abuse-limit logs.

## 6. Conversation Memory

Conversation memory is enabled with both the global setting and the active bot
profile's `memory_enabled` flag:

```env
MEMORY_ENABLED=true
MEMORY_RECENT_MESSAGES=10
MEMORY_COMPACTION_TRIGGER_MESSAGES=6
MEMORY_COMPACTION_SOURCE_MESSAGES=5
MEMORY_MAX_MESSAGE_CHARS=4000
MEMORY_COMPACTED_MAX_CHARS=2000
```

Memory is scoped by internal `users.id` and `bot_profile_id`, not by a shared
Telegram chat alone. Users can remove their recent and compacted memory with
`/memory_clear`; broader account deletion also clears memory.

## 7. LLM Provider Fallback

BotForge uses a small provider abstraction around model calls. By default,
`LLM_PRIMARY_PROVIDER=profile`, so the active bot profile selects the primary
provider with its `llm_provider` field. The `default_dev` profile uses Ollama;
the `nutrition` profile uses NVIDIA NIM. Set `LLM_PRIMARY_PROVIDER=ollama` or
`LLM_PRIMARY_PROVIDER=nvidia` only to force a global override. If the primary
provider is unavailable or returns an error, the engine tries the configured
fallback provider once and sends only that single answer to the user.

The request lifecycle also records how long a message waited before processing
started. When that wait is greater than `LLM_FALLBACK_QUEUE_WAIT_SECONDS`
(default: 100), BotForge selects the fallback provider immediately instead of
starting local inference.

NVIDIA NIM is configured with:

```env
LLM_FALLBACK_PROVIDER=nvidia
NVIDIA_API_KEY=<nvidia_api_key>
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5
```

The NVIDIA API Catalog exposes hosted NIM language models through
`POST /v1/chat/completions` at `https://integrate.api.nvidia.com`. Model names
and trial terms can change, so confirm the selected model in the catalog before
using it beyond development. BotForge logs the request id, selected provider,
fallback reason, and duration; it does not log API keys or raw user messages.

## 8. Create The First Invite Link

BotForge links Telegram users to invited email identities through invite links:

```text
https://t.me/<bot_username>?start=<invite_token>
```

Generate a beta invite link from the BotForge image, replacing
`<bot_username>` with the bot username from BotFather and `<email>` with the
recipient email:

```powershell
docker compose run --rm --no-deps botforge python -c "from forge_bot.database import create_invite_token; invite = create_invite_token(role='user', email='<email>', ttl_hours=24, bot_username='<bot_username>'); assert invite is not None; print(invite.invite_link)"
```

Only a bcrypt hash of the token is stored in PostgreSQL. Send the printed link
to the user who should join the beta. When the user opens it, Telegram sends
`/start <token>` to the bot automatically. The token is single-use and expires
after the selected TTL.

After invite redemption, BotForge shows the required usage policy summary.
Users can accept or decline immediately with Telegram inline buttons. The
fallback commands `/policy`, `/accept_policy`, and `/decline_policy` remain
available, and protected commands or AI chat stay blocked until the current
policy is accepted.

Policy acceptance is stored in `user_policy_acceptances` with the user id,
policy version, privacy notice version, timestamp, and source. Change
`BOT_POLICY_VERSION` or `BOT_PRIVACY_NOTICE_VERSION` to require users to accept
the new version. Optional analytics or training consent is separate and defaults
to disabled.

If the `t.me` preview page opens but does not pass the token after pressing
Start Bot, generate a direct Telegram app URI instead:

```powershell
docker compose run --rm --no-deps botforge python -c "from forge_bot.database import create_invite_token; invite = create_invite_token(role='user', email='<email>', ttl_hours=24, bot_username='<bot_username>'); assert invite is not None; print(invite.app_link)"
```

That prints a `tg://resolve?...` link, which opens the Telegram app directly and
avoids the browser preview page.

## 9. Admin Invite Management

After becoming an admin, use the `/invite` command to generate invite links without direct database access:

```text
/invite <role> <email>
```

**Usage:**

```text
/invite user person@example.com
```

**Response:**

```text
Invite link created.

Role: user
Email: person@example.com
Expires: 2026-05-09 12:00:00 UTC

Link:
https://t.me/my_bot?start=abcd1234...
```

**Available roles:**

- `user` - Standard beta user role
- `admin` - Admin role, including access to `/invite <role> <email>`
- `professional` - Reserved for future use; returns "not available"

**Requirements:**

- Only admins can use `/invite`
- Invites must include a valid email address
- Generated tokens are single-use and expire after `INVITE_TOKEN_TTL_HOURS` (default: 24 hours)
- Tokens are auditable: stored with `created_by_user_id` and `created_at` timestamps
- Each token can only be redeemed once (marked with `used_at` and `used_by_user_id`)

### Campaign Invite Links

Admins can also create public campaign invite links for events or promotions:

```text
/campaign_invite <role> <expires_at> <max_uses>
```

Example:

```text
/campaign_invite user 2026-06-30 100
```

Response:

```text
Campaign invite link created.

Role: user
Expires: 2026-06-30 23:59:59 UTC
Max uses: 100

Link:
https://t.me/my_bot?start=abcd1234...
```

The bot returns one reusable link. It can be redeemed until the end of the
expiration date in UTC or until the maximum use count is reached. Campaign
invite tokens are stored as hashes, and each redemption is recorded in
`invite_token_redemptions`.

Campaign invites support `user` and `admin`. The `professional` role remains
reserved and is rejected.

**Configuration:**

Set the invite token TTL via environment variable:

```bash
INVITE_TOKEN_TTL_HOURS=7  # Token expires after 7 days instead of 24 hours
CAMPAIGN_INVITE_MAX_USES_LIMIT=1000
```

To create the first local admin user during development, redeem an invite and
then set the linked user's `role` column to `admin`:

```sql
UPDATE users
SET role = 'admin'
WHERE username = '<bot_user>';
```

Alternatively, let Docker startup create the first admin invite. Set these in
`.env`, then run `docker compose up` and copy the printed invite link from the
`botforge` logs:

```env
BOOTSTRAP_ADMIN_EMAIL=you@example.com
BOOTSTRAP_BOT_USERNAME=<bot_username>
BOOTSTRAP_ADMIN_INVITE_TTL_HOURS=24
BOOTSTRAP_ADMIN_INVITE_FORCE=false
```

The startup bootstrap runs after migrations. It skips creation when an active
admin user already exists, and it also skips when an unused admin invite for the
same email is still valid. Set `BOOTSTRAP_ADMIN_INVITE_FORCE=true` only if you
lost the original link and need a new one.

Supported roles are `admin`, `professional`, and `user`. New users default to
`user`; `professional` is reserved for future behavior and does not grant admin
permissions.

Exit PostgreSQL:

```sql
\q
```

## 10. Telegram Smoke Test

Open a private chat with the bot in Telegram:

```text
/help
<open the invite link>
/status
hello
```

Only one running BotForge container should use the same Telegram token.

## Service Operations

### Production Readiness

Before inviting beta users, create `.env` from `.env.example` and verify:

```text
TELEGRAM_TOKEN is the real BotFather token and is not committed
BOTFORGE_ENV=production
DB_PASSWORD is not botforge_dev_password
POSTGRES_PASSWORD comes from DB_PASSWORD and is strong
BOT_PROFILE points to the intended beta profile
OLLAMA_MODEL matches the active profile's llm_model
BOT_ANALYTICS_CONSENT_ENABLED and BOT_TRAINING_CONSENT_ENABLED are intentional
postgres_data is a persistent named volume
ollama_data is a persistent named volume
a database backup has been created
restore has been tested into a clean local Docker volume
```

Never commit `.env`, raw Telegram tokens, provider credentials, database dumps,
or logs containing private user content.

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

### Database Backup

Database backups should include user records, roles, invite metadata, policy
acceptances, inbound message state, memory tables, and any future analytics
tables.
They should not include `.env`, local Ollama model caches, or generated logs.

Create a compressed PostgreSQL dump from the running Compose stack:

```bash
./scripts/backup_database.sh
```

By default the script writes `backups/botforge-postgres-<timestamp>.dump`.
The `backups/` directory and `*.dump` files are ignored by git.

To use a different local backup directory:

```bash
./scripts/backup_database.sh --backup-dir /var/backups/botforge
```

To target a non-default Compose project, pass `--project-name <name>`.

### Database Restore Test

Practice restores before beta. A simple local restore test is:

```bash
./scripts/backup_database.sh
docker compose -p botforge_restore_test up -d postgres
./scripts/restore_database.sh --project-name botforge_restore_test
docker compose -p botforge_restore_test exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
docker compose -p botforge_restore_test down -v
```

That uses a separate Compose project and volume so the normal local database is
not overwritten. With no `--backup-file`, the restore script uses the newest
`*.dump` file from `backups/`.

The restore script is destructive. It restores into the running `postgres`
service with `pg_restore --clean --if-exists --no-owner`.

After restoring, run a smoke test:

```bash
docker compose exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
docker compose logs --tail=100 botforge
```

Confirm expected users, invites, policy acceptances, and inbound message rows
are present before trusting the backup procedure.

### Restart And Rollback Basics

For a normal restart, use:

```bash
docker compose restart botforge
```

For a code rollback, check out the previous known-good revision, rebuild only
the bot image, and keep the database volume in place:

```bash
git checkout <known-good-revision>
docker compose up -d --build botforge
docker compose logs -f botforge
```

If a migration was already applied, restore the latest tested backup into a
clean PostgreSQL volume instead of editing migration state by hand.

### Secret Rotation

If the Telegram token leaks:

1. Open BotFather and revoke/regenerate the token immediately.
2. Stop BotForge so the leaked token is no longer used:
   `docker compose stop botforge`.
3. Update `TELEGRAM_TOKEN` in the uncommitted `.env`.
4. Start the bot again with `docker compose up -d botforge`.
5. Check `docker compose logs --tail=100 botforge` for startup errors.
6. Search recent commits, PRs, issues, chat logs, and deployment notes for the
   leaked token. Remove or rotate any copied secret.

If Ollama or future provider credentials leak, rotate them with the provider,
update `.env`, restart BotForge, and avoid posting the old values in issue
comments or logs.

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

Run checks after installing development dependencies.

The full beta release gate, including manual Docker, invite, privacy, restart,
backup/restore, rollback, and sign-off steps, lives in
[docs/beta-release-checklist.md](docs/beta-release-checklist.md).

Code quality checks (CI: `lint.yml`):

```bash
python -m ruff format --check src tests
python -m ruff check src tests
python -m black --check src tests
python -m isort --check-only src tests
python -m mypy src
python -m bandit -r src -ll
python -m radon cc src tests -s -a
```

Tests (CI: `tests.yml`):

```bash
python -m pytest
```

## Current Limitations

- Conversation memory is bounded to the latest configured raw messages plus a
  compacted summary. It is not vector search and does not retrieve arbitrary old
  facts beyond what was compacted.
- Telegram updates that were never delivered to the bot and are older than
  Telegram's pending-update retention window cannot be recovered.
- Provider/model selection is profile-driven by default. `default_dev` uses
  Ollama with `gemma3:4b`; `nutrition` uses NVIDIA NIM with the configured
  `NVIDIA_MODEL`.
- The application uses Telegram polling, so it should run as one active bot
  container per Telegram token.

## License

BotForge is licensed under the PolyForm Noncommercial License 1.0.0.

You are free to use, study, and modify the code for personal, educational, or
research purposes. Commercial use requires explicit written permission.

See [LICENSE](LICENSE) for the license text.
