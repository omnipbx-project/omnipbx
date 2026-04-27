from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SetupWizardPayload(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    country: str = Field(min_length=2, max_length=64)
    timezone: str = Field(min_length=2, max_length=64)
    default_language: str = Field(min_length=2, max_length=32)
    dialing_region: str = Field(min_length=1, max_length=16)
    deployment_mode: str = Field(pattern="^(office|public_server|advanced)$")
    access_mode: str = Field(pattern="^(local_network|public_domain|public_ip|private_self_hosted|http_only)$")
    behind_nat: bool = True
    external_host: str | None = Field(default=None, max_length=255)
    ssl_mode: str = Field(pattern="^(http|public_domain|public_ip|internal_local|custom_certificate)$")
    ssl_contact_email: str | None = None
    admin_username: str = Field(min_length=3, max_length=64)
    admin_password: str = Field(min_length=10, max_length=128)
    admin_email: str | None = Field(default=None, max_length=255)
    sip_port: int = Field(ge=1, le=65535)
    rtp_start: int = Field(ge=1024, le=65535)
    rtp_end: int = Field(ge=1024, le=65535)
    local_networks: str | None = Field(default=None, max_length=500)
    first_extension: str | None = Field(default=None, max_length=32)
    first_extension_name: str | None = Field(default=None, max_length=128)
    first_extension_secret: str | None = Field(default=None, max_length=128)

    @field_validator(
        "company_name",
        "country",
        "timezone",
        "default_language",
        "dialing_region",
        "external_host",
        "admin_username",
        "admin_password",
        "admin_email",
        "local_networks",
        "first_extension",
        "first_extension_name",
        "first_extension_secret",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("ssl_contact_email", "admin_email")
    @classmethod
    def validate_email(cls, value: str | None, info) -> str | None:
        ssl_mode = info.data.get("ssl_mode")
        field_name = info.field_name
        if field_name == "ssl_contact_email" and ssl_mode in {"public_domain", "public_ip"} and value is None:
            raise ValueError("A contact email is required for public domain SSL.")
        if value and "@" not in value:
            raise ValueError("Enter a valid contact email.")
        return value

    @field_validator("external_host")
    @classmethod
    def host_required_for_tls_modes(cls, value: str | None, info) -> str | None:
        access_mode = info.data.get("access_mode")
        ssl_mode = info.data.get("ssl_mode")
        if access_mode in {"local_network", "public_domain", "public_ip", "private_self_hosted"} and not value:
            raise ValueError("Enter the PBX IP address or domain name users should open.")
        if ssl_mode in {"public_domain", "public_ip", "internal_local", "custom_certificate"} and not value:
            raise ValueError("A host or IP is required for HTTPS modes.")
        return value

    @field_validator("rtp_end")
    @classmethod
    def validate_rtp_range(cls, value: int, info) -> int:
        rtp_start = info.data.get("rtp_start")
        if rtp_start is not None and value < rtp_start:
            raise ValueError("RTP end port must be greater than or equal to RTP start port.")
        return value

    @field_validator("local_networks")
    @classmethod
    def normalize_local_networks(cls, value: str | None) -> str | None:
        if not value:
            return None
        networks = [item.strip() for item in value.split(",") if item.strip()]
        return ", ".join(networks) if networks else None
