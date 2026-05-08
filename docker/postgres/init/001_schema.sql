CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NULL,
    telegram_id BIGINT NULL UNIQUE,
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invite_tokens (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NULL,
    used_by_user_id INTEGER NULL REFERENCES users(id),
    created_by_user_id INTEGER NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_invite_tokens_token_hash
ON invite_tokens (token_hash);

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
    UNIQUE (user_id, policy_version, privacy_notice_version, source)
);

CREATE INDEX IF NOT EXISTS ix_user_policy_acceptances_user_version
ON user_policy_acceptances (user_id, policy_version, privacy_notice_version);
