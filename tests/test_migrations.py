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
