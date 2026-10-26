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
    department_id: int | None


class ViewAsBy(ORMModel):
    """Администратор, который смотрит портал глазами другого сотрудника."""

    id: int
    display_name: str


class ViewAsIn(BaseModel):
    user_id: int


class SessionOut(BaseModel):
    user: UserOut
    view_as_by: ViewAsBy | None = None  # задано в режиме «Открыть как пользователь»: user — тот, чьими глазами смотрят
    app_name: str
    app_subtitle: str = "Аренда техники"
    insight_mode: str
    catalog_refresh_sec: int = 15


class AuthConfigOut(BaseModel):
    app_name: str
    bouncer_enabled: bool
    local_enabled: bool
    dev_enabled: bool
