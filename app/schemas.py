import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
# Paths the app itself uses; they cannot be used as short codes.
RESERVED_ALIASES = {"docs", "redoc", "openapi.json", "health", "auth", "links", "static", "favicon.ico"}


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt ignores bytes beyond 72


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Links ----------
class LinkCreate(BaseModel):
    url: HttpUrl
    custom_alias: str | None = None
    expires_at: datetime | None = None

    @field_validator("custom_alias")
    @classmethod
    def validate_alias(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not ALIAS_RE.fullmatch(value):
            raise ValueError("Alias must be 3-32 characters: letters, numbers, '-' or '_'")
        if value.lower() in RESERVED_ALIASES:
            raise ValueError("This alias is reserved")
        return value

    @field_validator("expires_at")
    @classmethod
    def must_be_in_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return value


class LinkOut(BaseModel):
    id: int
    code: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None
    is_active: bool


class LinkList(BaseModel):
    items: list[LinkOut]
    total: int
    limit: int
    offset: int


class DayCount(BaseModel):
    date: str
    clicks: int


class NameCount(BaseModel):
    name: str
    clicks: int


class LinkStats(BaseModel):
    link_id: int
    code: str
    total_clicks: int
    clicks_per_day: list[DayCount]
    top_referrers: list[NameCount]
    devices: list[NameCount]
