from pydantic import BaseModel, Field


class CallbackFollowupUpdate(BaseModel):
    completed: bool
    callback_number: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
