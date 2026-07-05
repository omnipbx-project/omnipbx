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
    codecs VARCHAR(200) NOT NULL DEFAULT 'ulaw,alaw,opus',
    video_codecs VARCHAR(200) NOT NULL DEFAULT '',
    call_recording_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    auto_provision_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    simultaneous_device_limit INTEGER NOT NULL DEFAULT 1,
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

CREATE TABLE IF NOT EXISTS cdr_raw (
    id BIGSERIAL PRIMARY KEY,
    calldate TIMESTAMPTZ,
    uniqueid VARCHAR(150) NOT NULL UNIQUE,
    linkedid VARCHAR(150),
    src VARCHAR(80),
    dst VARCHAR(80),
    clid VARCHAR(120),
    channel VARCHAR(120),
    dstchannel VARCHAR(120),
    dcontext VARCHAR(120),
    lastapp VARCHAR(80),
    lastdata TEXT,
    duration INTEGER,
    billsec INTEGER,
    disposition VARCHAR(45),
    amaflags VARCHAR(20),
    accountcode VARCHAR(80),
    peeraccount VARCHAR(80),
    userfield TEXT,
    sequence INTEGER,
    recordingfile VARCHAR(255),
    direction VARCHAR(20),
    trunk_name VARCHAR(80),
    route_name VARCHAR(80),
    queue_name VARCHAR(80),
    ivr_name VARCHAR(80),
    caller_extension VARCHAR(20),
    callee_extension VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cdr_raw_calldate ON cdr_raw (calldate DESC);
CREATE INDEX IF NOT EXISTS idx_cdr_raw_linkedid ON cdr_raw (linkedid);
CREATE INDEX IF NOT EXISTS idx_cdr_raw_direction ON cdr_raw (direction);

CREATE TABLE IF NOT EXISTS autodialer_campaigns (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL UNIQUE,
    trunk_name VARCHAR(80) NOT NULL,
    dialing_mode VARCHAR(20) NOT NULL DEFAULT 'preview',
    next_call_wait_seconds INTEGER NOT NULL DEFAULT 5,
    assigned_users JSONB NOT NULL DEFAULT '[]'::jsonb,
    assigned_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS autodialer_leads (
    id BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES autodialer_campaigns(id) ON DELETE CASCADE,
    lead_name VARCHAR(160) NOT NULL,
    phone_number VARCHAR(40) NOT NULL,
    dial_number VARCHAR(40),
    company VARCHAR(160),
    email VARCHAR(255),
    note TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_call_at TIMESTAMPTZ,
    last_result VARCHAR(80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, phone_number)
);

CREATE INDEX IF NOT EXISTS idx_autodialer_leads_campaign_status ON autodialer_leads (campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_autodialer_leads_created_at ON autodialer_leads (created_at DESC);

CREATE TABLE IF NOT EXISTS cel_raw (
    id BIGSERIAL PRIMARY KEY,
    eventtype VARCHAR(40),
    eventtime TIMESTAMPTZ,
    cid_name VARCHAR(120),
    cid_num VARCHAR(80),
    cid_ani VARCHAR(80),
    cid_rdnis VARCHAR(80),
    cid_dnid VARCHAR(80),
    exten VARCHAR(80),
    context VARCHAR(120),
    channame VARCHAR(160),
    appname VARCHAR(120),
    appdata TEXT,
    amaflags VARCHAR(20),
    accountcode VARCHAR(80),
    peeraccount VARCHAR(80),
    uniqueid VARCHAR(150),
    linkedid VARCHAR(150),
    userfield TEXT,
    peer VARCHAR(160),
    extra TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cel_raw_eventtime ON cel_raw (eventtime DESC);
CREATE INDEX IF NOT EXISTS idx_cel_raw_linkedid ON cel_raw (linkedid);
CREATE INDEX IF NOT EXISTS idx_cel_raw_uniqueid ON cel_raw (uniqueid);
CREATE INDEX IF NOT EXISTS idx_cel_raw_eventtype ON cel_raw (eventtype);

CREATE TABLE IF NOT EXISTS callback_followups (
    linkedid VARCHAR(150) PRIMARY KEY,
    callback_number VARCHAR(80),
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    assigned_to VARCHAR(120),
    assigned_at TIMESTAMPTZ,
    completed_by VARCHAR(120),
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS advanced_security_rules (
    id BIGSERIAL PRIMARY KEY,
    rule_type VARCHAR(40) NOT NULL,
    value VARCHAR(160) NOT NULL,
    note TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(rule_type, value)
);

CREATE TABLE IF NOT EXISTS app_security_failures (
    id BIGSERIAL PRIMARY KEY,
    subject_type VARCHAR(20) NOT NULL,
    subject_value VARCHAR(160) NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(subject_type, subject_value)
);

CREATE TABLE IF NOT EXISTS app_security_bans (
    id BIGSERIAL PRIMARY KEY,
    subject_type VARCHAR(20) NOT NULL,
    subject_value VARCHAR(160) NOT NULL,
    reason TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    banned_until TIMESTAMPTZ NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(subject_type, subject_value)
);

CREATE INDEX IF NOT EXISTS idx_app_security_bans_active ON app_security_bans (subject_type, subject_value, enabled, banned_until);
CREATE INDEX IF NOT EXISTS idx_app_security_failures_subject ON app_security_failures (subject_type, subject_value);

CREATE TABLE IF NOT EXISTS advanced_custom_config (
    config_key VARCHAR(40) PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS advanced_network_settings (
    id SMALLINT PRIMARY KEY,
    trusted_ips TEXT NOT NULL DEFAULT '',
    blocked_ips TEXT NOT NULL DEFAULT '',
    open_ports TEXT NOT NULL DEFAULT '',
    note TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO advanced_custom_config (config_key, content, enabled)
VALUES ('pjsip', '', FALSE), ('dialplan', '', FALSE)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO advanced_network_settings (id, trusted_ips, blocked_ips, open_ports, note)
VALUES (1, '', '', '5060/udp,10000-20000/udp,3478/tcp,3478/udp,49160-49200/udp,18000/tcp', '')
ON CONFLICT (id) DO NOTHING;
