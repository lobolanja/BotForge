"""create nutrition daily logs

Revision ID: 20260524_0010
Revises: 20260524_0009
Create Date: 2026-05-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260524_0010"
down_revision: str | Sequence[str] | None = "20260524_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store one editable nutrition day state per user/profile/date."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS nutrition_daily_logs (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            bot_profile_id TEXT NOT NULL,
            log_date DATE NOT NULL,
            plan_id TEXT NULL,
            situation_key TEXT NULL,
            situation_updated_at TIMESTAMPTZ NULL,
            meals JSONB NOT NULL DEFAULT '{}'::jsonb,
            notes JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT nutrition_daily_logs_user_profile_date_unique
                UNIQUE (user_id, bot_profile_id, log_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_nutrition_daily_logs_user_profile_date
        ON nutrition_daily_logs (user_id, bot_profile_id, log_date DESC)
        """
    )


def downgrade() -> None:
    """Remove nutrition daily log storage."""
    op.execute("DROP INDEX IF EXISTS ix_nutrition_daily_logs_user_profile_date")
    op.execute("DROP TABLE IF EXISTS nutrition_daily_logs")
