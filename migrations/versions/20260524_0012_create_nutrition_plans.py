"""create nutrition plan storage

Revision ID: 20260524_0012
Revises: 20260524_0011
Create Date: 2026-05-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260524_0012"
down_revision: str | Sequence[str] | None = "20260524_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store active nutrition plans and their normalized JSON documents."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS nutrition_plans (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL,
            source_filename TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (status IN ('draft', 'active', 'failed', 'archived'))
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_nutrition_plans_one_active_per_user
        ON nutrition_plans (user_id)
        WHERE status = 'active'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_nutrition_plans_user_status_updated
        ON nutrition_plans (user_id, status, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS nutrition_plan_documents (
            id BIGSERIAL PRIMARY KEY,
            plan_id UUID NOT NULL REFERENCES nutrition_plans(id) ON DELETE CASCADE,
            document_type TEXT NOT NULL,
            content JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (document_type IN ('meal_plan'))
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_nutrition_plan_documents_plan_type
        ON nutrition_plan_documents (plan_id, document_type)
        """
    )


def downgrade() -> None:
    """Remove nutrition plan storage."""
    op.execute("DROP INDEX IF EXISTS ux_nutrition_plan_documents_plan_type")
    op.execute("DROP TABLE IF EXISTS nutrition_plan_documents")
    op.execute("DROP INDEX IF EXISTS ix_nutrition_plans_user_status_updated")
    op.execute("DROP INDEX IF EXISTS ux_nutrition_plans_one_active_per_user")
    op.execute("DROP TABLE IF EXISTS nutrition_plans")
