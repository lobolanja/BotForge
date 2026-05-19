"""create conversation memory tables

Revision ID: 20260519_0008
Revises: 20260518_0007
Create Date: 2026-05-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260519_0008"
down_revision: str | Sequence[str] | None = "20260518_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store recent raw messages and compacted per-user memory."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            bot_profile_id TEXT NOT NULL,
            telegram_chat_id BIGINT NULL,
            telegram_message_id BIGINT NULL,
            inbound_message_id INTEGER NULL REFERENCES inbound_messages(id),
            request_id TEXT NULL,
            role VARCHAR(32) NOT NULL,
            content TEXT NOT NULL,
            content_chars INTEGER NOT NULL,
            summarized_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMPTZ NULL,
            CONSTRAINT conversation_messages_role_check
                CHECK (role IN ('user', 'assistant'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_messages_user_profile_created
        ON conversation_messages (user_id, bot_profile_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_messages_deleted_at
        ON conversation_messages (deleted_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_memory_summaries (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            bot_profile_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            source_message_count INTEGER NOT NULL DEFAULT 0,
            compaction_version TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMPTZ NULL,
            UNIQUE (user_id, bot_profile_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_memory_summaries_user_profile
        ON user_memory_summaries (user_id, bot_profile_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_memory_summaries_deleted_at
        ON user_memory_summaries (deleted_at)
        """
    )


def downgrade() -> None:
    """Remove conversation memory storage."""
    op.execute("DROP INDEX IF EXISTS ix_user_memory_summaries_deleted_at")
    op.execute("DROP INDEX IF EXISTS ix_user_memory_summaries_user_profile")
    op.execute("DROP TABLE IF EXISTS user_memory_summaries")
    op.execute("DROP INDEX IF EXISTS ix_conversation_messages_deleted_at")
    op.execute("DROP INDEX IF EXISTS ix_conversation_messages_user_profile_created")
    op.execute("DROP TABLE IF EXISTS conversation_messages")
