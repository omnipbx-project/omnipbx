from pydantic import BaseModel, Field


class ExtensionCreate(BaseModel):
    extension: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    display_name: str = Field(min_length=1, max_length=128)
    secret: str | None = Field(default=None, min_length=8, max_length=128)
    transport: str = "transport-udp"
    call_recording_enabled: bool = True
    auto_provision_enabled: bool = False
    simultaneous_device_limit: int = Field(default=1, ge=1, le=10)
    enabled: bool = True


class ExtensionRead(BaseModel):
    id: int
    extension: str
    display_name: str
    secret: str
    context: str
    transport: str
    codecs: str
    video_codecs: str
    call_recording_enabled: bool
    auto_provision_enabled: bool
    simultaneous_device_limit: int
    enabled: bool
