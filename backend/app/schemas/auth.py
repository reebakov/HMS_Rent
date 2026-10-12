from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=256)


class UserOut(ORMModel):
    id: int
    username: str
    display_name: str
    email: str | None
    avatar_url: str | None
    auth_source: str
    role: str


class SessionOut(BaseModel):
    user: UserOut
    app_name: str
    insight_mode: str


class AuthConfigOut(BaseModel):
    """Что показать на экране входа ещё до авторизации."""

    app_name: str
    google_enabled: bool
    google_domains: list[str]
    local_enabled: bool
    dev_enabled: bool
