"""create invite token authentication tables

Revision ID: 20260507_0003
Revises: 20260507_0002
Create Date: 2026-05-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260507_0003"
down_revision: str | Sequence[str] | None = "20260507_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add invite-token auth while keeping existing user records valid."""
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'user'
        """
    )
    op.execute("ALTER TABLE users ALTER COLUMN password DROP NOT NULL")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS invite_tokens (
            id SERIAL PRIMARY KEY,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            role VARCHAR(32) NOT NULL DEFAULT 'user',
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ NULL,
            used_by_user_id INTEGER NULL REFERENCES users(id),
            created_by_user_id INTEGER NULL REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_invite_tokens_token_hash
        ON invite_tokens (token_hash)
        """
    )


def downgrade() -> None:
    """Remove invite-token auth schema."""
    op.execute("DROP INDEX IF EXISTS ix_invite_tokens_token_hash")
    op.execute("DROP TABLE IF EXISTS invite_tokens")
    op.execute("UPDATE users SET password = '' WHERE password IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN password SET NOT NULL")
