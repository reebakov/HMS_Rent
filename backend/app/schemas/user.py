from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.common import DepartmentShort, InputModel, ORMModel, reject_explicit_null


class UserAdminOut(ORMModel):
    id: int
    username: str
    display_name: str
    email: str | None
    auth_source: str
    role: str
    is_active: bool
    department: DepartmentShort | None
    last_login_at: datetime | None


class UserCreate(InputModel):
    email: str = Field(min_length=5, max_length=128, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str | None = Field(default=None, max_length=255)
    department_id: int | None = None


class UserUpdate(InputModel):
    department_id: int | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _no_null(self):
        reject_explicit_null(self, "is_active")
        return self
