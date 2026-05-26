"""add langchain chat history window index

Revision ID: 20260524_0011
Revises: 20260524_0010
Create Date: 2026-05-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260524_0011"
down_revision: str | Sequence[str] | None = "20260524_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Support bounded recent-message and compaction-window reads."""
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_langchain_chat_history_session_id_id
        ON langchain_chat_history (session_id, id)
        """
    )


def downgrade() -> None:
    """Remove bounded-window read index."""
    op.execute("DROP INDEX IF EXISTS idx_langchain_chat_history_session_id_id")
