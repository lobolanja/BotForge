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
);

CREATE INDEX IF NOT EXISTS ix_inbound_messages_status_created_at
ON inbound_messages (status, created_at);

CREATE INDEX IF NOT EXISTS ix_inbound_messages_chat_user_message
ON inbound_messages (chat_id, telegram_user_id, telegram_message_id);

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
);

CREATE INDEX IF NOT EXISTS ix_conversation_messages_user_profile_created
ON conversation_messages (user_id, bot_profile_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_conversation_messages_deleted_at
ON conversation_messages (deleted_at);

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
);

CREATE INDEX IF NOT EXISTS ix_user_memory_summaries_user_profile
ON user_memory_summaries (user_id, bot_profile_id);

CREATE INDEX IF NOT EXISTS ix_user_memory_summaries_deleted_at
ON user_memory_summaries (deleted_at);
