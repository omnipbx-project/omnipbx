from collections.abc import Generator

import psycopg

from app.core.settings import get_settings


def get_connection() -> Generator[psycopg.Connection, None, None]:
    settings = get_settings()
    with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
        yield connection


def initialize_schema() -> None:
    settings = get_settings()
    ddl = """
    CREATE TABLE IF NOT EXISTS extensions (
        id BIGSERIAL PRIMARY KEY,
        extension VARCHAR(32) NOT NULL UNIQUE,
        display_name VARCHAR(128) NOT NULL,
        secret VARCHAR(128) NOT NULL,
        context VARCHAR(64) NOT NULL DEFAULT 'omnipbx-internal',
        transport VARCHAR(40) NOT NULL DEFAULT 'transport-udp',
        codecs VARCHAR(200) NOT NULL DEFAULT 'ulaw,alaw,g722',
        video_codecs VARCHAR(200) NOT NULL DEFAULT '',
        call_recording_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        auto_provision_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        simultaneous_device_limit INTEGER NOT NULL DEFAULT 1,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS trunks (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        provider_name VARCHAR(120),
        main_number VARCHAR(80),
        host VARCHAR(255) NOT NULL,
        username VARCHAR(80),
        password VARCHAR(128),
        transport VARCHAR(40) NOT NULL DEFAULT 'transport-udp',
        register_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        match_ip VARCHAR(80),
        codecs VARCHAR(200) NOT NULL DEFAULT 'ulaw,alaw',
        outbound_prefix VARCHAR(20),
        strip_digits INTEGER NOT NULL DEFAULT 0,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS inbound_routes (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        trunk_name VARCHAR(80) NOT NULL,
        did_pattern VARCHAR(80),
        destination_type VARCHAR(20) NOT NULL,
        destination_value VARCHAR(80) NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ring_groups (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        extension VARCHAR(20) NOT NULL UNIQUE,
        ring_strategy VARCHAR(20) NOT NULL DEFAULT 'ringall',
        ring_timeout INTEGER NOT NULL DEFAULT 20,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ring_group_members (
        ring_group_id BIGINT NOT NULL,
        extension VARCHAR(20) NOT NULL,
        position INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (ring_group_id, extension)
    );

    CREATE TABLE IF NOT EXISTS queues_custom (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        extension VARCHAR(20) NOT NULL UNIQUE,
        strategy VARCHAR(20) NOT NULL DEFAULT 'ringall',
        timeout INTEGER NOT NULL DEFAULT 20,
        retry INTEGER NOT NULL DEFAULT 5,
        wrapuptime INTEGER NOT NULL DEFAULT 0,
        max_wait_time INTEGER,
        announce_position BOOLEAN NOT NULL DEFAULT FALSE,
        musicclass VARCHAR(80) NOT NULL DEFAULT 'default',
        moh_file_name VARCHAR(255),
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        voicemail_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        voicemail_mailbox VARCHAR(80),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS queue_members_custom (
        queue_id BIGINT NOT NULL,
        extension VARCHAR(20) NOT NULL,
        member_order INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (queue_id, extension)
    );

    CREATE TABLE IF NOT EXISTS ivr_menus (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        extension VARCHAR(20) NOT NULL UNIQUE,
        prompt VARCHAR(255) NOT NULL,
        timeout INTEGER NOT NULL DEFAULT 5,
        invalid_retries INTEGER NOT NULL DEFAULT 2,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ivr_options (
        ivr_id BIGINT NOT NULL,
        digit VARCHAR(5) NOT NULL,
        destination_type VARCHAR(20) NOT NULL,
        destination_value VARCHAR(80) NOT NULL,
        PRIMARY KEY (ivr_id, digit)
    );

    CREATE TABLE IF NOT EXISTS working_hours (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        start_day VARCHAR(20) NOT NULL,
        end_day VARCHAR(20) NOT NULL,
        start_time VARCHAR(5) NOT NULL,
        end_time VARCHAR(5) NOT NULL,
        inbound_route_name VARCHAR(80) NOT NULL UNIQUE,
        after_hours_sound VARCHAR(255),
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS welcome_messages (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        sound_name VARCHAR(255) NOT NULL,
        inbound_route_name VARCHAR(80) NOT NULL UNIQUE,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS call_routing_rules (
        id BIGSERIAL PRIMARY KEY,
        section_slug VARCHAR(80) NOT NULL,
        item_slug VARCHAR(80) NOT NULL,
        name VARCHAR(120) NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (section_slug, item_slug, name)
    );

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

    ALTER TABLE cdr_raw ADD COLUMN IF NOT EXISTS dcontext VARCHAR(120);
    ALTER TABLE cdr_raw ADD COLUMN IF NOT EXISTS accountcode VARCHAR(80);
    ALTER TABLE cdr_raw ADD COLUMN IF NOT EXISTS peeraccount VARCHAR(80);
    ALTER TABLE cdr_raw ADD COLUMN IF NOT EXISTS userfield TEXT;
    ALTER TABLE cdr_raw ADD COLUMN IF NOT EXISTS sequence INTEGER;

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

    ALTER TABLE callback_followups ADD COLUMN IF NOT EXISTS status VARCHAR(24) NOT NULL DEFAULT 'open';
    ALTER TABLE callback_followups ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(120);
    ALTER TABLE callback_followups ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ;
    ALTER TABLE callback_followups ADD COLUMN IF NOT EXISTS completed_by VARCHAR(120);

    CREATE TABLE IF NOT EXISTS softphone_settings (
        id SMALLINT PRIMARY KEY,
        enabled BOOLEAN NOT NULL DEFAULT FALSE,
        websocket_url VARCHAR(500),
        sip_domain VARCHAR(255),
        display_name_prefix VARCHAR(120),
        public_host VARCHAR(255),
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS softphone_extension_state (
        extension VARCHAR(20) PRIMARY KEY,
        dnd_enabled BOOLEAN NOT NULL DEFAULT FALSE,
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

    CREATE TABLE IF NOT EXISTS api_push_settings (
        id SMALLINT PRIMARY KEY,
        enabled BOOLEAN NOT NULL DEFAULT FALSE,
        call_logs_url VARCHAR(500),
        callbacks_url VARCHAR(500),
        public_base_url VARCHAR(500),
        api_key VARCHAR(255),
        timeout_seconds INTEGER NOT NULL DEFAULT 10,
        poll_interval_seconds INTEGER NOT NULL DEFAULT 30,
        verify_ssl BOOLEAN NOT NULL DEFAULT TRUE,
        batch_limit INTEGER NOT NULL DEFAULT 200,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS api_push_state (
        entity_type VARCHAR(20) NOT NULL,
        entity_key VARCHAR(150) NOT NULL,
        payload_hash CHAR(64) NOT NULL,
        last_status VARCHAR(20) NOT NULL DEFAULT 'pending',
        retry_count INTEGER NOT NULL DEFAULT 0,
        dead_letter BOOLEAN NOT NULL DEFAULT FALSE,
        last_error TEXT,
        next_retry_at TIMESTAMPTZ,
        last_pushed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (entity_type, entity_key)
    );

    CREATE TABLE IF NOT EXISTS api_push_dead_letters (
        id BIGSERIAL PRIMARY KEY,
        entity_type VARCHAR(20) NOT NULL,
        entity_key VARCHAR(150) NOT NULL,
        target_url VARCHAR(500),
        payload_hash CHAR(64) NOT NULL,
        payload_json JSONB NOT NULL,
        error_message TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        last_attempt_at TIMESTAMPTZ,
        resolved BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (entity_type, entity_key)
    );

    CREATE TABLE IF NOT EXISTS api_push_test_payloads (
        id BIGSERIAL PRIMARY KEY,
        entity_type VARCHAR(20) NOT NULL,
        source_ip VARCHAR(80),
        api_key VARCHAR(255),
        headers_json JSONB,
        payload_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS system_settings (
        id SMALLINT PRIMARY KEY,
        setup_completed BOOLEAN NOT NULL DEFAULT FALSE,
        company_name VARCHAR(160) NOT NULL DEFAULT 'OmniPBX',
        country VARCHAR(64) NOT NULL DEFAULT 'Bangladesh',
        timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
        default_language VARCHAR(32) NOT NULL DEFAULT 'en',
        dialing_region VARCHAR(16) NOT NULL DEFAULT '+880',
        deployment_mode VARCHAR(32) NOT NULL DEFAULT 'office',
        access_mode VARCHAR(32) NOT NULL DEFAULT 'local_network',
        behind_nat BOOLEAN NOT NULL DEFAULT TRUE,
        external_host VARCHAR(255),
        ssl_mode VARCHAR(32) NOT NULL DEFAULT 'http',
        ssl_contact_email VARCHAR(255),
        admin_email VARCHAR(255),
        sip_port INTEGER NOT NULL DEFAULT 5060,
        rtp_start INTEGER NOT NULL DEFAULT 10000,
        rtp_end INTEGER NOT NULL DEFAULT 10100,
        local_networks VARCHAR(500),
        public_base_url VARCHAR(500),
        caddy_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS admin_users (
        id BIGSERIAL PRIMARY KEY,
        username VARCHAR(64) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(255),
        role VARCHAR(20) NOT NULL DEFAULT 'admin',
        is_owner BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS smtp_settings (
        id SMALLINT PRIMARY KEY,
        enabled BOOLEAN NOT NULL DEFAULT FALSE,
        mail_from VARCHAR(255),
        mail_from_name VARCHAR(255),
        mail_username VARCHAR(255),
        mail_server VARCHAR(255),
        mail_port INTEGER NOT NULL DEFAULT 587,
        mail_starttls BOOLEAN NOT NULL DEFAULT TRUE,
        mail_ssl_tls BOOLEAN NOT NULL DEFAULT FALSE,
        use_credentials BOOLEAN NOT NULL DEFAULT TRUE,
        validate_certs BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id BIGSERIAL PRIMARY KEY,
        admin_user_id BIGINT NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
        token_hash CHAR(64) NOT NULL UNIQUE,
        requested_ip VARCHAR(80),
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_password_reset_admin_user ON password_reset_tokens (admin_user_id);
    CREATE INDEX IF NOT EXISTS idx_password_reset_expires_at ON password_reset_tokens (expires_at);

    CREATE TABLE IF NOT EXISTS admin_audit_log (
        id BIGSERIAL PRIMARY KEY,
        event_type VARCHAR(80) NOT NULL,
        actor_admin_id BIGINT,
        actor_username VARCHAR(64),
        target_kind VARCHAR(80),
        target_value VARCHAR(120),
        message TEXT,
        details_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at ON admin_audit_log (created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_admin_audit_log_event_type ON admin_audit_log (event_type);

    CREATE TABLE IF NOT EXISTS internal_secrets (
        key_name VARCHAR(80) PRIMARY KEY,
        secret_value VARCHAR(255) NOT NULL,
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
    """
    with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(ddl)
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS deployment_mode VARCHAR(32) NOT NULL DEFAULT 'office'")
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS access_mode VARCHAR(32) NOT NULL DEFAULT 'local_network'")
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS behind_nat BOOLEAN NOT NULL DEFAULT TRUE")
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS country VARCHAR(64) NOT NULL DEFAULT 'Bangladesh'")
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS default_language VARCHAR(32) NOT NULL DEFAULT 'en'")
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS dialing_region VARCHAR(16) NOT NULL DEFAULT '+880'")
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS admin_email VARCHAR(255)")
            cursor.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS local_networks VARCHAR(500)")
            cursor.execute("ALTER TABLE extensions ADD COLUMN IF NOT EXISTS transport VARCHAR(40) NOT NULL DEFAULT 'transport-udp'")
            cursor.execute("ALTER TABLE extensions ADD COLUMN IF NOT EXISTS codecs VARCHAR(200) NOT NULL DEFAULT 'ulaw,alaw,g722'")
            cursor.execute("ALTER TABLE extensions ADD COLUMN IF NOT EXISTS video_codecs VARCHAR(200) NOT NULL DEFAULT ''")
            cursor.execute("ALTER TABLE extensions ADD COLUMN IF NOT EXISTS call_recording_enabled BOOLEAN NOT NULL DEFAULT FALSE")
            cursor.execute("ALTER TABLE extensions ADD COLUMN IF NOT EXISTS auto_provision_enabled BOOLEAN NOT NULL DEFAULT FALSE")
            cursor.execute("ALTER TABLE extensions ADD COLUMN IF NOT EXISTS simultaneous_device_limit INTEGER NOT NULL DEFAULT 1")
            cursor.execute("ALTER TABLE advanced_security_rules ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE")
            cursor.execute("ALTER TABLE advanced_security_rules ADD COLUMN IF NOT EXISTS note TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_security_bans_active ON app_security_bans (subject_type, subject_value, enabled, banned_until)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_security_failures_subject ON app_security_failures (subject_type, subject_value)")
            cursor.execute("ALTER TABLE trunks ADD COLUMN IF NOT EXISTS main_number VARCHAR(80)")
            cursor.execute("ALTER TABLE inbound_routes ALTER COLUMN destination_value TYPE VARCHAR(255)")
            cursor.execute("ALTER TABLE extensions ALTER COLUMN codecs SET DEFAULT 'ulaw,alaw,g722'")
            cursor.execute("ALTER TABLE extensions ALTER COLUMN video_codecs SET DEFAULT ''")
            cursor.execute("UPDATE extensions SET transport = 'transport-udp' WHERE transport IS NULL OR transport = ''")
            cursor.execute("UPDATE extensions SET codecs = 'ulaw,alaw,g722' WHERE transport = 'transport-udp' AND (codecs IS NULL OR codecs = '' OR codecs = 'ulaw,alaw')")
            cursor.execute("UPDATE extensions SET codecs = 'ulaw,alaw' WHERE transport = 'transport-udp-softphone' AND (codecs IS NULL OR codecs = '' OR codecs = 'ulaw,alaw,g722' OR codecs = 'g722,ulaw,alaw' OR codecs = 'opus,g722,ulaw,alaw')")
            cursor.execute("UPDATE extensions SET codecs = 'ulaw' WHERE transport = 'transport-wss' AND (codecs IS NULL OR codecs = '' OR codecs = 'ulaw,alaw' OR codecs = 'ulaw,alaw,g722' OR codecs = 'g722,ulaw,alaw' OR codecs = 'opus,g722,ulaw,alaw' OR codecs = 'opus,ulaw')")
            cursor.execute("UPDATE extensions SET video_codecs = '' WHERE video_codecs IS NULL")
            cursor.execute("UPDATE extensions SET video_codecs = 'h264,vp8' WHERE transport = 'transport-udp-softphone' AND video_codecs = ''")
            cursor.execute("UPDATE extensions SET video_codecs = '' WHERE transport = 'transport-wss'")
            cursor.execute("UPDATE extensions SET auto_provision_enabled = TRUE WHERE transport = 'transport-wss'")
            cursor.execute("UPDATE extensions SET auto_provision_enabled = FALSE WHERE transport <> 'transport-wss'")
            cursor.execute("UPDATE extensions SET simultaneous_device_limit = 1 WHERE simultaneous_device_limit IS NULL OR simultaneous_device_limit < 1")
            cursor.execute("UPDATE extensions SET simultaneous_device_limit = 10 WHERE simultaneous_device_limit > 10")
            cursor.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'admin'")
            cursor.execute(
                """
                INSERT INTO softphone_settings (id, enabled, websocket_url, sip_domain, display_name_prefix, public_host, note)
                VALUES (1, FALSE, NULL, NULL, 'OmniPBX', NULL, NULL)
                ON CONFLICT (id) DO NOTHING
                """
            )
            cursor.execute("UPDATE admin_users SET role = 'owner' WHERE is_owner = TRUE")
            cursor.execute("UPDATE admin_users SET role = 'admin' WHERE is_owner = FALSE AND role NOT IN ('owner', 'admin', 'read_only')")
            cursor.execute("UPDATE admin_users SET is_owner = TRUE WHERE role = 'owner'")
            cursor.execute("UPDATE admin_users SET is_owner = FALSE WHERE role = 'admin' OR role = 'read_only'")
            cursor.execute(
                """
                INSERT INTO user_permissions (name, description, features)
                VALUES
                    ('User', 'Can use their own phone, voicemail, contacts, and personal call history.', '["Own phone", "Voicemail", "Contacts"]'::jsonb),
                    ('Supervisor', 'Can view team users, team call history, and basic reports.', '["Team users", "Team calls", "Reports"]'::jsonb),
                    ('Admin', 'Can manage users, groups, phone lines, call flow, reports, and settings.', '["Users", "Trunks", "Call flow", "Settings"]'::jsonb)
                ON CONFLICT (name) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO user_groups (name, description, permission_id)
                SELECT group_row.name, group_row.description, permission.id
                FROM (
                    VALUES
                        ('Sales', 'People who handle sales calls and customer follow-up.', 'User'),
                        ('Support', 'People who help customers and manage support calls.', 'Supervisor'),
                        ('Admin', 'People who manage the PBX system.', 'Admin')
                ) AS group_row(name, description, permission_name)
                LEFT JOIN user_permissions permission ON permission.name = group_row.permission_name
                ON CONFLICT (name) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO api_push_settings (
                    id, enabled, call_logs_url, callbacks_url, public_base_url, api_key,
                    timeout_seconds, poll_interval_seconds, verify_ssl, batch_limit
                )
                VALUES (1, FALSE, NULL, NULL, NULL, NULL, 10, 30, TRUE, 200)
                ON CONFLICT (id) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO system_settings (
                    id, setup_completed, company_name, country, timezone, default_language, dialing_region,
                    deployment_mode, access_mode, behind_nat, external_host, ssl_mode, ssl_contact_email, admin_email,
                    sip_port, rtp_start, rtp_end, local_networks, public_base_url, caddy_enabled
                )
                VALUES (
                    1, FALSE, 'OmniPBX', 'Bangladesh', 'UTC', 'en', '+880',
                    'office', 'local_network', TRUE, NULL, 'http', NULL, NULL,
                    5060, 10000, 10100, NULL, NULL, FALSE
                )
                ON CONFLICT (id) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO smtp_settings (
                    id, enabled, mail_from, mail_from_name, mail_username, mail_server,
                    mail_port, mail_starttls, mail_ssl_tls, use_credentials, validate_certs
                )
                VALUES (1, FALSE, NULL, 'OmniPBX', NULL, NULL, 587, TRUE, FALSE, TRUE, TRUE)
                ON CONFLICT (id) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO advanced_custom_config (config_key, content, enabled)
                VALUES
                    ('pjsip', '', FALSE),
                    ('dialplan', '', FALSE)
                ON CONFLICT (config_key) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO advanced_network_settings (id, trusted_ips, blocked_ips, open_ports, note)
                VALUES (1, '', '', '5060/udp,10000-10100/udp,18000/tcp', '')
                ON CONFLICT (id) DO NOTHING
                """
            )
