"""add langchain postgres chat memory tables

Revision ID: 20260524_0009
Revises: 20260519_0008
Create Date: 2026-05-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260524_0009"
down_revision: str | Sequence[str] | None = "20260519_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create LangChain's Postgres chat-history table plus user mapping."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS langchain_chat_history (
            id SERIAL PRIMARY KEY,
            session_id UUID NOT NULL,
            message JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_langchain_chat_history_session_id
        ON langchain_chat_history (session_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS langchain_chat_sessions (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            bot_profile_id TEXT NOT NULL,
            session_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, bot_profile_id),
            UNIQUE (session_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_chat_sessions_user_profile
        ON langchain_chat_sessions (user_id, bot_profile_id)
        """
    )


def downgrade() -> None:
    """Remove LangChain chat memory tables."""
    op.execute("DROP INDEX IF EXISTS ix_langchain_chat_sessions_user_profile")
    op.execute("DROP TABLE IF EXISTS langchain_chat_sessions")
    op.execute("DROP INDEX IF EXISTS idx_langchain_chat_history_session_id")
    op.execute("DROP TABLE IF EXISTS langchain_chat_history")
