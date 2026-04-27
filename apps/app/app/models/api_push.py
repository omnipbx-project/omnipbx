from pydantic import BaseModel, Field


class ApiPushSettingsPayload(BaseModel):
    enabled: bool = False
    call_logs_url: str | None = Field(default=None, max_length=500)
    callbacks_url: str | None = Field(default=None, max_length=500)
    public_base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=255)
    timeout_seconds: int = Field(default=10, ge=3, le=120)
    poll_interval_seconds: int = Field(default=30, ge=5, le=300)
    verify_ssl: bool = True
    batch_limit: int = Field(default=200, ge=1, le=1000)
