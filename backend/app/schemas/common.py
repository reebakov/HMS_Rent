from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from app.core import clock


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InputModel(BaseModel):
    """Тело запроса: пробелы по краям строк обрезаются до проверки длины, поэтому «   » не проходит min_length."""

    model_config = ConfigDict(str_strip_whitespace=True)


def reject_explicit_null(model: BaseModel, *fields: str) -> None:
    """PATCH: поле можно не присылать, но нельзя прислать null — колонка NOT NULL (иначе IntegrityError, а не 422)."""
    for name in fields:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"Поле «{name}» не может быть null")


def _not_in_past(value: date) -> date:
    if value < clock.today():
        raise ValueError("Дата возврата не может быть в прошлом")
    return value


# Срок возврата ПК или ВМ: «сегодня» — по часовому поясу портала
ReturnDate = Annotated[date, AfterValidator(_not_in_past)]


class UserShort(ORMModel):
    id: int
    username: str
    display_name: str


class DepartmentShort(ORMModel):
    id: int
    name: str


class ComputerShort(ORMModel):
    id: int
    name: str
    tier: str
    is_virtual: bool
    cpu: str | None
    ram_gb: int | None
    storage: str | None
    gpu: str | None
