CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NULL,
    password VARCHAR(255) NULL,
    telegram_id BIGINT NULL UNIQUE,
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invite_tokens (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    token_type VARCHAR(32) NOT NULL DEFAULT 'single_use',
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    email VARCHAR(255) NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NULL,
    used_by_user_id INTEGER NULL REFERENCES users(id),
    max_uses INTEGER NOT NULL DEFAULT 1,
    used_count INTEGER NOT NULL DEFAULT 0,
    created_by_user_id INTEGER NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT invite_tokens_type_check
        CHECK (token_type IN ('single_use', 'campaign')),
    CONSTRAINT invite_tokens_uses_check
        CHECK (max_uses > 0 AND used_count >= 0 AND used_count <= max_uses)
);

CREATE INDEX IF NOT EXISTS ix_invite_tokens_token_hash
ON invite_tokens (token_hash);

CREATE TABLE IF NOT EXISTS invite_token_redemptions (
    id SERIAL PRIMARY KEY,
    invite_token_id INTEGER NOT NULL REFERENCES invite_tokens(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (invite_token_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_invite_token_redemptions_invite_token_id
ON invite_token_redemptions (invite_token_id);

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
