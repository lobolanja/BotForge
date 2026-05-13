"""add campaign invite tokens

Revision ID: 20260512_0005
Revises: 20260508_0004
Create Date: 2026-05-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260512_0005"
down_revision: str | Sequence[str] | None = "20260508_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add reusable campaign invite support and redemption audit rows."""
    op.execute("ALTER TABLE invite_tokens ALTER COLUMN email DROP NOT NULL")
    op.execute(
        """
        ALTER TABLE invite_tokens
        ADD COLUMN IF NOT EXISTS token_type VARCHAR(32) NOT NULL DEFAULT 'single_use'
        """
    )
    op.execute(
        """
        ALTER TABLE invite_tokens
        ADD COLUMN IF NOT EXISTS max_uses INTEGER NOT NULL DEFAULT 1
        """
    )
    op.execute(
        """
        ALTER TABLE invite_tokens
        ADD COLUMN IF NOT EXISTS used_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'invite_tokens_type_check'
            ) THEN
                ALTER TABLE invite_tokens
                ADD CONSTRAINT invite_tokens_type_check
                CHECK (token_type IN ('single_use', 'campaign'));
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'invite_tokens_uses_check'
            ) THEN
                ALTER TABLE invite_tokens
                ADD CONSTRAINT invite_tokens_uses_check
                CHECK (max_uses > 0 AND used_count >= 0 AND used_count <= max_uses);
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS invite_token_redemptions (
            id SERIAL PRIMARY KEY,
            invite_token_id INTEGER NOT NULL REFERENCES invite_tokens(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            redeemed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (invite_token_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_invite_token_redemptions_invite_token_id
        ON invite_token_redemptions (invite_token_id)
        """
    )


def downgrade() -> None:
    """Remove campaign invite support."""
    op.execute("DROP INDEX IF EXISTS ix_invite_token_redemptions_invite_token_id")
    op.execute("DROP TABLE IF EXISTS invite_token_redemptions")
    op.execute(
        "ALTER TABLE invite_tokens DROP CONSTRAINT IF EXISTS invite_tokens_uses_check"
    )
    op.execute(
        "ALTER TABLE invite_tokens DROP CONSTRAINT IF EXISTS invite_tokens_type_check"
    )
    op.execute("ALTER TABLE invite_tokens DROP COLUMN IF EXISTS used_count")
    op.execute("ALTER TABLE invite_tokens DROP COLUMN IF EXISTS max_uses")
    op.execute("ALTER TABLE invite_tokens DROP COLUMN IF EXISTS token_type")
