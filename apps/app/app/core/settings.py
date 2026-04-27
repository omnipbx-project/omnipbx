from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OmniPBX"
    app_version: str = "0.1.0"
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "omnipbx"
    db_user: str = "omnipbx"
    db_password: str = "change-me"
    http_port: int = 8000
    public_http_port: int = 80
    public_https_port: int = 443
    sip_port: int = 5060
    rtp_start: int = 10000
    rtp_end: int = 10100
    internal_context: str = "omnipbx-internal"
    generated_config_dir: str = "/etc/asterisk/generated"
    pjsip_generated_file: str = "/etc/asterisk/generated/pjsip.generated.conf"
    pjsip_trunks_generated_file: str = "/etc/asterisk/generated/pjsip.trunks.generated.conf"
    extensions_generated_file: str = "/etc/asterisk/generated/extensions.generated.conf"
    trunks_generated_file: str = "/etc/asterisk/generated/extensions.trunks.generated.conf"
    inbound_routes_generated_file: str = "/etc/asterisk/generated/inbound_routes.generated.conf"
    ring_groups_generated_file: str = "/etc/asterisk/generated/ring_groups.generated.conf"
    queues_generated_file: str = "/etc/asterisk/generated/queues.generated.conf"
    queues_dialplan_generated_file: str = "/etc/asterisk/generated/queues_dialplan.generated.conf"
    ivrs_generated_file: str = "/etc/asterisk/generated/ivrs.generated.conf"
    musiconhold_generated_file: str = "/etc/asterisk/generated/musiconhold.generated.conf"
    custom_sounds_dir: str = "/var/lib/asterisk/sounds/custom"
    moh_root_dir: str = "/var/lib/asterisk/moh"
    cdr_custom_file: str = "/var/log/asterisk/cdr-custom/omnipbx.csv"
    recordings_dir: str = "/var/spool/asterisk/monitor"
    runtime_dir: str = "/var/lib/omnipbx"
    host_project_path: str = "/opt/omnipbx-host"
    caddyfile_path: str = "/var/lib/omnipbx/caddy/Caddyfile"
    caddy_internal_root_path: str = "/var/lib/caddy-data/caddy/pki/authorities/local/root.crt"
    host_preflight_path: str = "/var/lib/omnipbx/host-preflight.json"
    asterisk_reload_command: str = "core reload"
    update_check_interval_seconds: int = 3600
    update_check_timeout_seconds: int = 20
    update_status_path: str = "/var/lib/omnipbx/update-status.json"
    update_check_cache_path: str = "/var/lib/omnipbx/update-check.json"

    model_config = SettingsConfigDict(
        env_prefix="OMNIPBX_",
        extra="ignore",
    )

    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.db_host} "
            f"port={self.db_port} "
            f"dbname={self.db_name} "
            f"user={self.db_user} "
            f"password={self.db_password}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
