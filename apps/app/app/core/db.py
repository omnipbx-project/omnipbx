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
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS trunks (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        provider_name VARCHAR(120),
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
        lastapp VARCHAR(80),
        lastdata TEXT,
        duration INTEGER,
        billsec INTEGER,
        disposition VARCHAR(45),
        amaflags VARCHAR(20),
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

    CREATE TABLE IF NOT EXISTS callback_followups (
        linkedid VARCHAR(150) PRIMARY KEY,
        callback_number VARCHAR(80),
        completed BOOLEAN NOT NULL DEFAULT FALSE,
        completed_at TIMESTAMPTZ,
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

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
