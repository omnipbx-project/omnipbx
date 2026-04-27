from pydantic import BaseModel, Field, model_validator


ALLOWED_TRANSPORTS = {"transport-udp"}


class TrunkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    provider_name: str | None = Field(default=None, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=80)
    password: str | None = Field(default=None, max_length=128)
    transport: str = "transport-udp"
    register_enabled: bool = True
    match_ip: str | None = Field(default=None, max_length=80)
    codecs: str = Field(default="ulaw,alaw", min_length=1, max_length=200)
    outbound_prefix: str | None = Field(default=None, max_length=20, pattern=r"^[0-9]+$")
    strip_digits: int = Field(default=0, ge=0, le=20)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_trunk(self):
        self.name = self.name.strip().lower()
        self.host = self.host.strip()
        self.provider_name = self.provider_name.strip() if self.provider_name else None
        self.username = self.username.strip() if self.username else None
        self.password = self.password.strip() if self.password else None
        self.match_ip = self.match_ip.strip() if self.match_ip else None
        self.codecs = self.codecs.strip()

        if self.transport not in ALLOWED_TRANSPORTS:
            raise ValueError("Only transport-udp is supported in Phase 1.")
        if self.register_enabled and (not self.username or not self.password):
            raise ValueError("Username and password are required when registration is enabled.")
        if self.strip_digits and not self.outbound_prefix:
            raise ValueError("Outbound prefix is required when strip digits is used.")
        return self


class TrunkRead(BaseModel):
    id: int
    name: str
    provider_name: str | None
    host: str
    username: str | None
    password: str | None
    transport: str
    register_enabled: bool
    match_ip: str | None
    codecs: str
    outbound_prefix: str | None
    strip_digits: int
    enabled: bool
