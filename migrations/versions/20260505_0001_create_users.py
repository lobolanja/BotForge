"""create users table

Revision ID: 20260505_0001
Revises:
Create Date: 2026-05-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260505_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial users table if it does not already exist.

    The migration is idempotent so it can coexist with the legacy Docker
    init SQL that may have already created the table in existing volumes.
    """
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            telegram_id BIGINT NULL UNIQUE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)


def downgrade() -> None:
    """Drop the users table created by this initial migration."""
    op.execute("DROP TABLE IF EXISTS users")
