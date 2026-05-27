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
    transport VARCHAR(40) NOT NULL DEFAULT 'transport-udp',
    codecs VARCHAR(200) NOT NULL DEFAULT 'ulaw,alaw,g722',
    video_codecs VARCHAR(200) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_permissions (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    features JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_groups (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    permission_id BIGINT REFERENCES user_permissions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_profiles (
    extension VARCHAR(32) PRIMARY KEY REFERENCES extensions(extension) ON UPDATE CASCADE ON DELETE CASCADE,
    email VARCHAR(255),
    photo_path VARCHAR(500),
    group_id BIGINT REFERENCES user_groups(id) ON DELETE SET NULL,
    permission_id BIGINT REFERENCES user_permissions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO user_permissions (name, description, features)
VALUES
    ('User', 'Can use their own phone, voicemail, contacts, and personal call history.', '["Own phone", "Voicemail", "Contacts"]'::jsonb),
    ('Supervisor', 'Can view team users, team call history, and basic reports.', '["Team users", "Team calls", "Reports"]'::jsonb),
    ('Admin', 'Can manage users, groups, phone lines, call flow, reports, and settings.', '["Users", "Trunks", "Call flow", "Settings"]'::jsonb)
ON CONFLICT (name) DO NOTHING;

INSERT INTO user_groups (name, description, permission_id)
SELECT group_row.name, group_row.description, permission.id
FROM (
    VALUES
        ('Sales', 'People who handle sales calls and customer follow-up.', 'User'),
        ('Support', 'People who help customers and manage support calls.', 'Supervisor'),
        ('Admin', 'People who manage the PBX system.', 'Admin')
) AS group_row(name, description, permission_name)
LEFT JOIN user_permissions permission ON permission.name = group_row.permission_name
ON CONFLICT (name) DO NOTHING;

INSERT INTO schema_migrations (version)
VALUES ('0001_bootstrap')
ON CONFLICT (version) DO NOTHING;
