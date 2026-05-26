"""split nutrition plan documents by source JSON

Revision ID: 20260524_0013
Revises: 20260524_0012
Create Date: 2026-05-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260524_0013"
down_revision: str | Sequence[str] | None = "20260524_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow active plans to store situaciones/comidas as separate JSONB docs."""
    op.execute(
        """
        ALTER TABLE nutrition_plan_documents
        DROP CONSTRAINT IF EXISTS nutrition_plan_documents_document_type_check
        """
    )
    op.execute(
        """
        ALTER TABLE nutrition_plan_documents
        ADD CONSTRAINT nutrition_plan_documents_document_type_check
        CHECK (
            document_type IN (
                'meal_plan',
                'situaciones',
                'comidas',
                'reglas_adaptacion',
                'recetas'
            )
        )
        """
    )


def downgrade() -> None:
    """Return to the original single meal_plan document type."""
    op.execute(
        """
        ALTER TABLE nutrition_plan_documents
        DROP CONSTRAINT IF EXISTS nutrition_plan_documents_document_type_check
        """
    )
    op.execute(
        """
        ALTER TABLE nutrition_plan_documents
        ADD CONSTRAINT nutrition_plan_documents_document_type_check
        CHECK (document_type IN ('meal_plan'))
        """
    )
