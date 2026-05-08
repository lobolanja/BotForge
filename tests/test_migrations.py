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
