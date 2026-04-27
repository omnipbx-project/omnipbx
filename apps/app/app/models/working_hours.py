import re

from pydantic import BaseModel, Field, field_validator


ALLOWED_WEEKDAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


class WorkingHoursCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start_day: str
    end_day: str
    start_time: str
    end_time: str
    inbound_route_name: str = Field(min_length=1, max_length=80)
    after_hours_sound: str | None = Field(default=None, max_length=255)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "-")
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Working hours name must use letters, numbers, underscore, or hyphen.")
        return cleaned

    @field_validator("start_day", "end_day")
    @classmethod
    def validate_day(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_WEEKDAYS:
            raise ValueError("Day must be a full weekday name.")
        return cleaned

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"\d{2}:\d{2}", cleaned):
            raise ValueError("Time must be in HH:MM format.")
        return cleaned

    @field_validator("inbound_route_name")
    @classmethod
    def validate_route_name(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Inbound route name contains unsupported characters.")
        return cleaned

    @field_validator("after_hours_sound", mode="before")
    @classmethod
    def normalize_after_hours_sound(cls, value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None


class WorkingHoursRead(BaseModel):
    id: int
    name: str
    start_day: str
    end_day: str
    start_time: str
    end_time: str
    inbound_route_name: str
    after_hours_sound: str | None
    enabled: bool
