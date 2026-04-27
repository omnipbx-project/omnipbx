from pydantic import BaseModel, Field, field_validator


ALLOWED_RING_GROUP_STRATEGIES = {"ringall", "linear"}


class RingGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    extension: str = Field(min_length=1, max_length=20)
    ring_strategy: str = "ringall"
    ring_timeout: int = Field(default=20, ge=1, le=300)
    enabled: bool = True
    members: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "-")
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Ring group name must use letters, numbers, underscore, or hyphen.")
        return cleaned

    @field_validator("extension")
    @classmethod
    def validate_extension(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.isdigit():
            raise ValueError("Ring group extension must be numeric.")
        return cleaned

    @field_validator("ring_strategy")
    @classmethod
    def validate_ring_strategy(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_RING_GROUP_STRATEGIES:
            raise ValueError("Ring group strategy must be ringall or linear.")
        return cleaned

    @field_validator("members")
    @classmethod
    def validate_members(cls, values: list[str]) -> list[str]:
        members: list[str] = []
        for item in values:
            cleaned = str(item).strip()
            if not cleaned:
                continue
            if not cleaned.isdigit():
                raise ValueError("Ring group members must be numeric extensions.")
            members.append(cleaned)
        return members


class RingGroupRead(BaseModel):
    id: int
    name: str
    extension: str
    ring_strategy: str
    ring_timeout: int
    enabled: bool
    members: list[str]
