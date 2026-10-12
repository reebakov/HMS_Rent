from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DepartmentOut(ORMModel):
    id: int
    name: str
    code: str | None
    head_name: str | None
    is_active: bool


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    head_name: str | None = Field(default=None, max_length=255)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    head_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
