from datetime import datetime

from pydantic import BaseModel, Field


class AuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    first_name: str | None
    username: str | None
    timezone: str
    accepted_terms_at: datetime | None
    notifications_enabled: bool = True
    created_at: datetime


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class SettingsIn(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    accept_terms: bool | None = None
    notifications_enabled: bool | None = None
