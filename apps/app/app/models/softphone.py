from pydantic import BaseModel, Field


class SoftphoneSettingsPayload(BaseModel):
    enabled: bool = False
    websocket_url: str | None = Field(default=None, max_length=500)
    sip_domain: str | None = Field(default=None, max_length=255)
    display_name_prefix: str | None = Field(default=None, max_length=120)
    public_host: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class SoftphoneDndPayload(BaseModel):
    enabled: bool
