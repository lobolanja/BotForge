"""add user deletion controls

Revision ID: 20260518_0007
Revises: 20260513_0006
Create Date: 2026-05-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260518_0007"
down_revision: str | Sequence[str] | None = "20260513_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Track deleted users and durable beta deletion requests."""
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL")
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ NULL
        """
    )
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_reason TEXT NULL")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_deletion_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            telegram_user_id BIGINT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'requested',
            requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            failure_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT user_deletion_requests_status_check
                CHECK (status IN ('requested', 'confirmed', 'completed', 'failed'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_deletion_requests_user_id
        ON user_deletion_requests (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_deletion_requests_status_requested_at
        ON user_deletion_requests (status, requested_at)
        """
    )


def downgrade() -> None:
    """Remove beta deletion request storage and deleted-user markers."""
    op.execute("DROP INDEX IF EXISTS ix_user_deletion_requests_status_requested_at")
    op.execute("DROP INDEX IF EXISTS ix_user_deletion_requests_user_id")
    op.execute("DROP TABLE IF EXISTS user_deletion_requests")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deletion_reason")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deletion_requested_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deleted_at")
