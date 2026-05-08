"""create policy acceptance audit table

Revision ID: 20260508_0004
Revises: 20260507_0003
Create Date: 2026-05-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260508_0004"
down_revision: str | Sequence[str] | None = "20260507_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store required policy acceptance separately from optional consents."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_policy_acceptances (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            policy_version VARCHAR(32) NOT NULL,
            privacy_notice_version VARCHAR(32) NOT NULL,
            accepted_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            source VARCHAR(32) NOT NULL,
            analytics_consent_accepted_at TIMESTAMPTZ NULL,
            analytics_consent_revoked_at TIMESTAMPTZ NULL,
            training_consent_accepted_at TIMESTAMPTZ NULL,
            training_consent_revoked_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (
                user_id,
                policy_version,
                privacy_notice_version,
                source
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_policy_acceptances_user_version
        ON user_policy_acceptances (
            user_id,
            policy_version,
            privacy_notice_version
        )
        """
    )


def downgrade() -> None:
    """Remove policy acceptance storage."""
    op.execute("DROP INDEX IF EXISTS ix_user_policy_acceptances_user_version")
    op.execute("DROP TABLE IF EXISTS user_policy_acceptances")
