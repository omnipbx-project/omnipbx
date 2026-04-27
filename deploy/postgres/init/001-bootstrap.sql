CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS extensions (
    id BIGSERIAL PRIMARY KEY,
    extension VARCHAR(32) NOT NULL UNIQUE,
    display_name VARCHAR(128) NOT NULL,
    secret VARCHAR(128) NOT NULL,
    context VARCHAR(64) NOT NULL DEFAULT 'omnipbx-internal',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version)
VALUES ('0001_bootstrap')
ON CONFLICT (version) DO NOTHING;
