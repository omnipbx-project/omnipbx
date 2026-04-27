from pydantic import BaseModel, Field, field_validator


ALLOWED_QUEUE_STRATEGIES = {"ringall", "leastrecent", "fewestcalls", "random", "rrmemory", "linear"}


class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    extension: str = Field(min_length=1, max_length=20)
    strategy: str = "ringall"
    timeout: int = Field(default=20, ge=0, le=300)
    retry: int = Field(default=5, ge=0, le=300)
    wrapuptime: int = Field(default=0, ge=0, le=300)
    max_wait_time: int | None = Field(default=None, ge=1, le=7200)
    announce_position: bool = False
    musicclass: str = "default"
    moh_file_name: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    voicemail_enabled: bool = False
    voicemail_mailbox: str | None = Field(default=None, max_length=80)
    members: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "-")
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Queue name must use letters, numbers, underscore, or hyphen.")
        return cleaned

    @field_validator("extension")
    @classmethod
    def validate_extension(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.isdigit():
            raise ValueError("Queue extension must be numeric.")
        return cleaned

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_QUEUE_STRATEGIES:
            raise ValueError("Unsupported queue strategy.")
        return cleaned

    @field_validator("musicclass", mode="before")
    @classmethod
    def normalize_musicclass(cls, value: str | None) -> str:
        cleaned = str(value or "default").strip().lower()
        return cleaned or "default"

    @field_validator("voicemail_mailbox", mode="before")
    @classmethod
    def normalize_mailbox(cls, value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None

    @field_validator("members")
    @classmethod
    def validate_members(cls, values: list[str]) -> list[str]:
        members: list[str] = []
        for item in values:
            cleaned = str(item).strip()
            if not cleaned:
                continue
            if not cleaned.isdigit():
                raise ValueError("Queue members must be numeric extensions.")
            members.append(cleaned)
        return members


class QueueRead(BaseModel):
    id: int
    name: str
    extension: str
    strategy: str
    timeout: int
    retry: int
    wrapuptime: int
    max_wait_time: int | None
    announce_position: bool
    musicclass: str
    moh_file_name: str | None
    enabled: bool
    voicemail_enabled: bool
    voicemail_mailbox: str | None
    members: list[str]
