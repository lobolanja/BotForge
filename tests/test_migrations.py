from pathlib import Path


def test_user_role_migration_defaults_existing_users_to_user() -> None:
    migration = Path("migrations/versions/20260507_0002_add_user_roles.py")
    contents = migration.read_text(encoding="utf-8")

    assert "role VARCHAR(32) NOT NULL DEFAULT 'user'" in contents
    assert "CHECK (role IN ('admin', 'professional', 'user'))" in contents
