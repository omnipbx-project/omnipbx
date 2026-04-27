from pydantic import BaseModel, Field, field_validator


class WelcomeMessageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sound_name: str = Field(min_length=1, max_length=255)
    inbound_route_name: str = Field(min_length=1, max_length=80)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "-")
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Welcome message name must use letters, numbers, underscore, or hyphen.")
        return cleaned

    @field_validator("sound_name")
    @classmethod
    def validate_sound_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Welcome prompt is required.")
        return cleaned

    @field_validator("inbound_route_name")
    @classmethod
    def validate_route_name(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Inbound route name contains unsupported characters.")
        return cleaned


class WelcomeMessageRead(BaseModel):
    id: int
    name: str
    sound_name: str
    inbound_route_name: str
    enabled: bool
