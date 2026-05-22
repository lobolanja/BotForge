# Beta Release Checklist

This checklist is the release gate for the first private beta. Run it on the
target branch before inviting real users. The goal is evidence: every pass/fail
note should let the project owner decide whether BotForge is safe enough for the
beta cut.

## Prerequisites

- A clean checkout of the target branch.
- Docker Engine and Docker Compose v2 available as `docker compose`.
- Python 3.10 or newer, matching the support policy in `pyproject.toml`.
- Development dependencies installed with `python -m pip install -e ".[dev]"`.
- A Telegram bot token from BotFather for manual Telegram smoke tests.
- Enough disk and memory for the configured Ollama model.

Record the release candidate before starting:

```text
Date:
Branch:
Commit:
Tester:
Environment:
Notes:
```

## Environment Setup

1. Start from a clean checkout of the target branch.
   - Pass: `git status --short` has no unexpected source changes.
   - Fail: unrelated or unexplained changes are present.
2. Confirm no real secrets are committed.
   - Pass: `.env` is ignored by git, `.env.example` contains placeholders only,
     and no Telegram token, provider API key, database dump, or private log file
     appears in tracked files.
   - Fail: any real credential or private runtime artifact is tracked.
3. Copy `.env.example` to `.env`.
   - Pass: `.env` exists locally and remains untracked.
   - Fail: `.env` is missing or appears in `git status`.
4. Fill required development values.
   - Pass: `TELEGRAM_TOKEN` is a real BotFather token, `DB_PASSWORD` is set, and
     `OLLAMA_MODEL` matches the active bot profile model.
   - Fail: required values are blank or still documented placeholders.
5. For beta or production-like validation, set `BOTFORGE_ENV=production` and use
   a non-development database password.
   - Pass: startup validation rejects documented development secrets.
   - Fail: production mode accepts placeholder tokens or the development
     database password.

## Automated Checks

Run this exact local sequence:

```bash
python -m ruff format --check src tests
python -m ruff check src tests
python -m black --check src tests
python -m isort --check-only src tests
python -m mypy src
python -m bandit -r src -ll
python -m radon cc src tests -s -a
python -m pytest
```

Required pass criteria:

- Ruff format, Ruff lint, Black, isort, mypy, Bandit, Radon, and pytest all exit
  with status 0.
- The migration smoke tests in `tests/test_migrations.py` pass.
- The configuration validation tests in `tests/test_config.py` and
  `tests/test_operations_hardening.py` pass.
- The command registration smoke test in `tests/test_command_imports.py` passes.
- The runtime log-safety tests in `tests/test_runtime_safety.py` pass.

CI pass criteria:

- `lint.yml` runs on pull requests into `main`.
- `tests.yml` runs on pull requests into `main`.
- The test workflow validates the oldest supported Python version from
  `pyproject.toml`.
- If `pyproject.toml` declares more than one supported Python version, CI either
  tests that policy or the declared support is narrowed before beta.

Result:

```text
Automated checks:
CI check links:
Failures or follow-up issues:
```

## Docker Smoke Test

Run these steps from the clean checkout.

1. Build and start the stack.
   ```bash
   docker compose up -d --build
   ```
   - Pass: build succeeds and Compose starts `botforge`, `postgres`, `ollama`,
     and `ollama-pull`.
   - Fail: any service exits unexpectedly.
2. Confirm service health.
   ```bash
   docker compose ps
   ```
   - Pass: PostgreSQL, Ollama, and BotForge health checks are healthy or still
     moving toward healthy within the documented startup window.
   - Fail: a service remains unhealthy.
3. Confirm PostgreSQL is reachable.
   ```bash
   docker compose exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
   ```
   - Pass: expected BotForge tables are listed.
   - Fail: database connection fails or tables are missing after migrations.
4. Confirm Ollama is reachable.
   ```bash
   docker compose exec ollama ollama list
   ```
   - Pass: the configured model is present, or fallback-provider behavior is
     intentionally configured and documented for this beta cut.
   - Fail: no model is available and no fallback path is configured.
5. Confirm BotForge logs show startup without secrets.
   ```bash
   docker compose logs --tail=100 botforge
   ```
   - Pass: logs show migration/startup progress without Telegram tokens,
     provider keys, database passwords, raw invite tokens, or full private
     messages.
   - Fail: logs expose secrets or private content.

## Invite And Onboarding Smoke Test

1. Create or seed the first admin with the documented development process.
   - Pass: the test Telegram user has admin role.
   - Fail: admin role cannot be established.
2. As admin, run:
   ```text
   /invite user user@example.com
   ```
   - Pass: the bot returns an invite link and clear metadata.
   - Fail: no link is generated or the error is unclear.
3. Confirm admin-only protection.
   - Pass: a non-admin user cannot run `/invite` or `/campaign_invite`.
   - Fail: normal users can create invites.
4. Inspect the database record for the invite.
   - Pass: only a bcrypt token hash is stored, not the raw invite token.
   - Fail: the raw token is stored in plaintext.
5. Open the invite as a test user.
   - Pass: the Telegram identity links to the invited user.
   - Fail: valid invite redemption fails.
6. Try invalid, expired, and already-used invite links.
   - Pass: each case returns a clear user-facing message.
   - Fail: errors are raw, confusing, or silently ignored.
7. Confirm policy gating.
   - Pass: the user sees the policy summary and cannot use protected chat before
     accepting via the inline buttons or `/accept_policy`.
   - Fail: protected chat works before policy acceptance or the policy text is
     missing.
8. Accept policy.
   ```text
   Tap "Accept policy" or run /accept_policy
   ```
   - Pass: protected chat works after acceptance.
   - Fail: acceptance is not persisted or chat remains blocked.

## Chat And Runtime Smoke Test

1. Send a normal domain message.
   - Pass: BotForge uses the active bot profile/system prompt and replies
     without raw technical errors.
   - Fail: the user sees stack traces, provider exceptions, or irrelevant
     profile behavior.
2. Send a second message while the first is processing.
   - Pass: waiting-state behavior is clear and only one final answer is sent for
     each accepted request.
   - Fail: duplicate answers, lost requests, or confusing queue messages appear.
3. Confirm typing action during processing.
   - Pass: Telegram shows typing while the LLM request is running.
   - Fail: long requests show no feedback.
4. Simulate or observe an Ollama timeout.
   - Pass: timeout produces a friendly fallback message or a configured fallback
     provider answer.
   - Fail: the user sees raw provider errors.
5. Simulate or observe Ollama failure.
   - Pass: failure produces one friendly response, not duplicate answers.
   - Fail: duplicated answers, raw exceptions, or no response.
6. Inspect logs after runtime tests.
   - Pass: logs include request ids, provider selection, durations, and counters
     without raw private message text.
   - Fail: logs expose full private messages or secrets.

## Restart And Recovery Smoke Test

1. Restart the bot container.
   ```bash
   docker compose restart botforge
   ```
   - Pass: the bot starts cleanly and user identity/policy state survives.
   - Fail: users must re-register unexpectedly.
2. Confirm persistent user state after restart.
   - Pass: `/status` or protected chat reflects the linked user and policy
     acceptance.
   - Fail: persisted state is missing.
3. Confirm unfinished-message recovery behavior.
   - Pass: stale or queued rows are retried, expired, or failed according to the
     documented recovery policy.
   - Fail: unfinished messages remain stuck without an operator-visible status.

## Backup And Restore Smoke Test

1. Run the backup script.
   ```bash
   ./scripts/backup_database.sh
   ```
   - Pass: a non-empty `backups/botforge-postgres-<timestamp>.dump` file is
     created and remains untracked by git.
   - Fail: no dump is created, the dump is empty, or it appears in `git status`.
2. Restore into a clean Compose project and volume.
   ```bash
   docker compose -p botforge_restore_test up -d postgres
   ./scripts/restore_database.sh --project-name botforge_restore_test
   docker compose -p botforge_restore_test exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
   ```
   - Pass: restore completes and expected tables are present.
   - Fail: restore fails or tables are missing.
3. Validate restored data.
   - Pass: users, invites, policy acceptances, and inbound message state expected
     for the test are present after restore.
   - Fail: expected records are missing.
4. Clean up the restore project.
   ```bash
   docker compose -p botforge_restore_test down -v
   ```
   - Pass: the test project is removed without touching the normal local stack.
   - Fail: the normal local database volume is affected.

Result:

```text
Backup file:
Restore project:
Validated tables/data:
Failures or follow-up issues:
```

## Privacy And Security Checklist

Before beta, verify each gate:

- No real Telegram token is committed.
- No provider API key is committed.
- `.env` is ignored.
- Development database password is not used in production or beta mode.
- Admin-only commands reject normal users.
- Invite tokens are hashed at rest.
- Policy acceptance is required before protected chat.
- Optional analytics consent defaults to false.
- Optional training consent defaults to false.
- Logs do not include raw invite tokens, database passwords, provider API keys,
  or full private messages.
- Rate limits are configured in `.env`.
- `/privacy` explains stored data categories and controls.
- `/memory_clear` is available if memory is included in the beta cut.
- `/delete_my_data` or a documented beta deletion request flow is available if
  data deletion is included in the beta cut.
- Data retention and deletion behavior is documented in
  `docs/privacy-and-retention.md`.
- Backup and restore have been tested.

Result:

```text
Privacy/security pass:
Failures or follow-up issues:
```

## Operational Checklist

Before beta, verify each gate:

- PostgreSQL data volume is persistent.
- Ollama model volume is persistent if local Ollama is part of deployment.
- Backup script creates a non-empty PostgreSQL dump.
- Restore script restores into a clean database.
- Rollback instructions are documented.
- Telegram token rotation steps are documented.
- Startup health checks pass.
- Failure logs are actionable without exposing secrets.

## Rollback Checklist

1. Identify the previous known-good revision.
   - Pass: commit hash or release tag is recorded.
   - Fail: no known-good revision is available.
2. Stop or drain BotForge if needed.
   ```bash
   docker compose stop botforge
   ```
3. Check out the known-good revision.
   ```bash
   git checkout <known-good-revision>
   ```
4. Rebuild and restart the bot while preserving the database volume.
   ```bash
   docker compose up -d --build botforge
   ```
5. Watch startup logs.
   ```bash
   docker compose logs -f botforge
   ```
   - Pass: startup succeeds and protected chat works for an existing test user.
   - Fail: rollback does not restore service.
6. If a bad migration already ran, restore the latest tested backup into a clean
   PostgreSQL volume instead of editing migration state by hand.
   - Pass: restored service has expected users, invites, policy acceptances, and
     message state.
   - Fail: restore cannot recover expected data.

## Token Rotation Checklist

If the Telegram token leaks:

1. Revoke or regenerate the token in BotFather immediately.
2. Stop BotForge.
   ```bash
   docker compose stop botforge
   ```
3. Update `TELEGRAM_TOKEN` in the uncommitted `.env`.
4. Start BotForge.
   ```bash
   docker compose up -d botforge
   ```
5. Check startup logs.
   ```bash
   docker compose logs --tail=100 botforge
   ```
6. Search recent commits, PRs, issues, chat logs, and deployment notes for copied
   leaked values. Remove exposed copies where possible and rotate any related
   credentials.

If a provider API key leaks, rotate it with the provider, update `.env`, restart
BotForge, and avoid pasting the old value into tickets or logs.

## Sign-Off

Complete this section after all checks are run.

```text
Release candidate:
Date:
Branch:
Commit:
Tester:

Automated checks:
CI status:
Docker smoke test:
Invite/onboarding smoke test:
Chat/runtime smoke test:
Restart/recovery smoke test:
Backup/restore smoke test:
Privacy/security gate:
Operational gate:
Rollback/token rotation docs:

Decision:
Follow-up issues:
Notes:
```

Beta can start only when the project owner accepts the remaining risk in the
decision field. Failures found during this checklist should become follow-up
issues instead of being hidden in release notes.
