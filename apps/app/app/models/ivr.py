import re

from pydantic import BaseModel, Field, field_validator


ALLOWED_IVR_DESTINATION_TYPES = {"extension", "trunk", "queue", "ivr", "ring_group"}


class IVROptionCreate(BaseModel):
    digit: str = Field(min_length=1, max_length=5)
    destination_type: str
    destination_value: str = Field(min_length=1, max_length=80)

    @field_validator("digit")
    @classmethod
    def validate_digit(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"[0-9*#]{1,5}", cleaned):
            raise ValueError("IVR digit must be 0-9, * or #.")
        return cleaned

    @field_validator("destination_type")
    @classmethod
    def validate_destination_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_IVR_DESTINATION_TYPES:
            raise ValueError("Unsupported IVR destination type.")
        return cleaned

    @field_validator("destination_value")
    @classmethod
    def validate_destination_value(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_#*.+-]{1,80}", cleaned):
            raise ValueError("IVR destination value contains unsupported characters.")
        return cleaned


class IvrCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    extension: str = Field(min_length=1, max_length=20)
    prompt: str = Field(min_length=1, max_length=255)
    timeout: int = Field(default=5, ge=1, le=60)
    invalid_retries: int = Field(default=2, ge=0, le=10)
    enabled: bool = True
    options: list[IVROptionCreate] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "-")
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("IVR name must use letters, numbers, underscore, or hyphen.")
        return cleaned

    @field_validator("extension")
    @classmethod
    def validate_extension(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.isdigit():
            raise ValueError("IVR extension must be numeric.")
        return cleaned

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("IVR prompt is required.")
        return cleaned


class IvrRead(BaseModel):
    id: int
    name: str
    extension: str
    prompt: str
    timeout: int
    invalid_retries: int
    enabled: bool
    options: list[IVROptionCreate]
