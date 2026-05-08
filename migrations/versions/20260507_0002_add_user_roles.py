"""add user roles

Revision ID: 20260507_0002
Revises: 20260505_0001
Create Date: 2026-05-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260507_0002"
down_revision: str | Sequence[str] | None = "20260505_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add role storage to users with user as the existing-row default."""
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'user'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'users_role_check'
            ) THEN
                ALTER TABLE users
                ADD CONSTRAINT users_role_check
                CHECK (role IN ('admin', 'professional', 'user'));
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Remove role storage from users."""
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role")
