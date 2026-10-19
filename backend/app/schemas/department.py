from pydantic import Field, model_validator

from app.schemas.common import InputModel, ORMModel, reject_explicit_null


class DepartmentOut(ORMModel):
    id: int
    name: str
    code: str | None
    head_name: str | None
    is_active: bool


class DepartmentCreate(InputModel):
    name: str = Field(min_length=2, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    head_name: str | None = Field(default=None, max_length=255)


class DepartmentUpdate(InputModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    head_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _no_null(self):
        reject_explicit_null(self, "name", "is_active")
        return self
