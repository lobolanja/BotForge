"""create inbound messages table

Revision ID: 20260513_0006
Revises: 20260512_0005
Create Date: 2026-05-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0006"
down_revision: str | Sequence[str] | None = "20260512_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist normalized Telegram inbound messages and processing state."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inbound_messages (
            id SERIAL PRIMARY KEY,
            telegram_update_id BIGINT NOT NULL UNIQUE,
            telegram_message_id BIGINT NOT NULL,
            chat_id BIGINT NOT NULL,
            telegram_user_id BIGINT NULL,
            message_type VARCHAR(32) NOT NULL,
            text TEXT NULL,
            file_id TEXT NULL,
            file_unique_id TEXT NULL,
            file_name TEXT NULL,
            mime_type TEXT NULL,
            file_size BIGINT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'persisted',
            received_at TIMESTAMPTZ NULL,
            persisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processing_started_at TIMESTAMPTZ NULL,
            processing_finished_at TIMESTAMPTZ NULL,
            answered_at TIMESTAMPTZ NULL,
            failed_at TIMESTAMPTZ NULL,
            failure_reason TEXT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            raw_update JSONB NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT inbound_messages_status_check
                CHECK (
                    status IN (
                        'received',
                        'persisted',
                        'ignored',
                        'queued',
                        'processing',
                        'answered',
                        'failed',
                        'expired'
                    )
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_inbound_messages_status_created_at
        ON inbound_messages (status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_inbound_messages_chat_user_message
        ON inbound_messages (chat_id, telegram_user_id, telegram_message_id)
        """
    )


def downgrade() -> None:
    """Remove inbound message persistence."""
    op.execute("DROP INDEX IF EXISTS ix_inbound_messages_chat_user_message")
    op.execute("DROP INDEX IF EXISTS ix_inbound_messages_status_created_at")
    op.execute("DROP TABLE IF EXISTS inbound_messages")
