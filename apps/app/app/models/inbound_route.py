import re

from pydantic import BaseModel, Field, model_validator


ALLOWED_DESTINATION_TYPES = {"extension", "trunk", "queue", "ivr", "ring_group"}


class InboundRouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    trunk_name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    did_pattern: str | None = Field(default=None, max_length=80)
    destination_type: str
    destination_value: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_#*.+-]+$")
    enabled: bool = True

    @model_validator(mode="after")
    def validate_route(self):
        self.name = self.name.strip().lower()
        self.trunk_name = self.trunk_name.strip().lower()
        self.did_pattern = self.did_pattern.strip() if self.did_pattern else None
        self.destination_type = self.destination_type.strip().lower()
        self.destination_value = self.destination_value.strip()
        if self.destination_type not in ALLOWED_DESTINATION_TYPES:
            raise ValueError("Unsupported inbound route destination type.")
        if self.did_pattern and not re.fullmatch(r"[A-Za-z0-9_.*#+-]+", self.did_pattern):
            raise ValueError("DID pattern contains unsupported characters.")
        return self


class InboundRouteRead(BaseModel):
    id: int
    name: str
    trunk_name: str
    did_pattern: str | None
    destination_type: str
    destination_value: str
    enabled: bool
