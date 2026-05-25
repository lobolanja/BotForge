from pathlib import Path


def test_user_role_migration_defaults_existing_users_to_user() -> None:
    migration = Path("migrations/versions/20260507_0002_add_user_roles.py")
    contents = migration.read_text(encoding="utf-8")

    assert "role VARCHAR(32) NOT NULL DEFAULT 'user'" in contents
    assert "CHECK (role IN ('admin', 'professional', 'user'))" in contents


def test_policy_acceptance_migration_tracks_required_and_optional_consent() -> None:
    migration = Path("migrations/versions/20260508_0004_create_policy_acceptances.py")
    contents = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260508_0004"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260507_0003"' in contents
    assert "CREATE TABLE IF NOT EXISTS user_policy_acceptances" in contents
    assert "policy_version VARCHAR(32) NOT NULL" in contents
    assert "privacy_notice_version VARCHAR(32) NOT NULL" in contents
    assert "accepted_at TIMESTAMPTZ NOT NULL" in contents
    assert "analytics_consent_accepted_at TIMESTAMPTZ NULL" in contents
    assert "training_consent_accepted_at TIMESTAMPTZ NULL" in contents


def test_invite_token_migration_follows_role_migration() -> None:
    migration = Path("migrations/versions/20260507_0003_create_invite_tokens.py")
    contents = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260507_0003"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260507_0002"' in contents
    assert "ADD COLUMN IF NOT EXISTS email VARCHAR(255) NULL" in contents
    assert "email VARCHAR(255) NULL" in contents


def test_campaign_invite_migration_tracks_limited_reuse() -> None:
    migration = Path("migrations/versions/20260512_0005_add_campaign_invites.py")
    contents = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260512_0005"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260508_0004"' in contents
    assert "ALTER TABLE invite_tokens ALTER COLUMN email DROP NOT NULL" in contents
    assert "token_type VARCHAR(32) NOT NULL DEFAULT 'single_use'" in contents
    assert "max_uses INTEGER NOT NULL DEFAULT 1" in contents
    assert "used_count INTEGER NOT NULL DEFAULT 0" in contents
    assert "CREATE TABLE IF NOT EXISTS invite_token_redemptions" in contents


def test_user_deletion_controls_migration_tracks_soft_delete_and_requests() -> None:
    migration = Path("migrations/versions/20260518_0007_add_user_deletion_controls.py")
    contents = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260518_0007"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260513_0006"' in contents
    assert "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL" in contents
    assert "ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ NULL" in contents
    assert "CREATE TABLE IF NOT EXISTS user_deletion_requests" in contents
    assert (
        "CHECK (status IN ('requested', 'confirmed', 'completed', 'failed'))"
        in contents
    )


def test_conversation_memory_migration_tracks_recent_and_compacted_memory() -> None:
    migration = Path("migrations/versions/20260519_0008_create_conversation_memory.py")
    contents = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260519_0008"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260518_0007"' in contents
    assert "CREATE TABLE IF NOT EXISTS conversation_messages" in contents
    assert "bot_profile_id TEXT NOT NULL" in contents
    assert "summarized_at TIMESTAMPTZ NULL" in contents
    assert "CHECK (role IN ('user', 'assistant'))" in contents
    assert "CREATE TABLE IF NOT EXISTS user_memory_summaries" in contents
    assert "UNIQUE (user_id, bot_profile_id)" in contents


def test_langchain_chat_memory_migration_uses_official_history_schema() -> None:
    migration = Path("migrations/versions/20260524_0009_add_langchain_chat_memory.py")
    contents = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260524_0009"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260519_0008"' in contents
    assert "CREATE TABLE IF NOT EXISTS langchain_chat_history" in contents
    assert "session_id UUID NOT NULL" in contents
    assert "message JSONB NOT NULL" in contents
    assert "idx_langchain_chat_history_session_id" in contents
    assert "ON langchain_chat_history (session_id)" in contents
    assert "ON langchain_chat_history (session_id, id)" not in contents
    assert "CREATE TABLE IF NOT EXISTS langchain_chat_sessions" in contents


def test_nutrition_daily_logs_migration_tracks_editable_day_state() -> None:
    migration = Path(
        "migrations/versions/20260524_0010_create_nutrition_daily_logs.py"
    )

    contents = migration.read_text()

    assert 'revision: str = "20260524_0010"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260524_0009"' in contents
    assert "CREATE TABLE IF NOT EXISTS nutrition_daily_logs" in contents
    assert "user_id INTEGER NOT NULL REFERENCES users(id)" in contents
    assert "situation_key TEXT NULL" in contents
    assert "situation_updated_at TIMESTAMPTZ NULL" in contents
    assert "meals JSONB NOT NULL DEFAULT '{}'::jsonb" in contents
    assert "UNIQUE (user_id, bot_profile_id, log_date)" in contents


def test_langchain_history_window_index_migration_supports_bounded_reads() -> None:
    migration = Path(
        "migrations/versions/20260524_0011_add_langchain_history_window_index.py"
    )

    contents = migration.read_text()

    assert 'revision: str = "20260524_0011"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260524_0010"' in contents
    assert "idx_langchain_chat_history_session_id_id" in contents
    assert "ON langchain_chat_history (session_id, id)" in contents


def test_nutrition_plan_storage_migration_tracks_active_user_plan() -> None:
    migration = Path("migrations/versions/20260524_0012_create_nutrition_plans.py")

    contents = migration.read_text()

    assert 'revision: str = "20260524_0012"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260524_0011"' in contents
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in contents
    assert "CREATE TABLE IF NOT EXISTS nutrition_plans" in contents
    assert "user_id INTEGER NOT NULL REFERENCES users(id)" in contents
    assert "status IN ('draft', 'active', 'failed', 'archived')" in contents
    assert "ux_nutrition_plans_one_active_per_user" in contents
    assert "CREATE TABLE IF NOT EXISTS nutrition_plan_documents" in contents
    assert "document_type IN ('meal_plan')" in contents


def test_nutrition_plan_document_split_migration_tracks_source_documents() -> None:
    migration = Path(
        "migrations/versions/20260524_0013_split_nutrition_plan_documents.py"
    )

    contents = migration.read_text()

    assert 'revision: str = "20260524_0013"' in contents
    assert 'down_revision: str | Sequence[str] | None = "20260524_0012"' in contents
    assert "nutrition_plan_documents_document_type_check" in contents
    assert "'situaciones'" in contents
    assert "'comidas'" in contents
    assert "'reglas_adaptacion'" in contents
    assert "'recetas'" in contents
