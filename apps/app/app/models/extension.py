from pydantic import BaseModel, Field


class ExtensionCreate(BaseModel):
    extension: str = Field(min_length=2, max_length=32, pattern=r"^[0-9]+$")
    display_name: str = Field(min_length=1, max_length=128)
    secret: str | None = Field(default=None, min_length=8, max_length=128)
    enabled: bool = True


class ExtensionRead(BaseModel):
    id: int
    extension: str
    display_name: str
    secret: str
    context: str
    enabled: bool

