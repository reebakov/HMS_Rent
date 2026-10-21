from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.core import clock
from app.schemas.common import InputModel, ORMModel, ReturnDate


class RequestCreate(InputModel):
    booking_id: int | None = None
    vm_id: int | None = None
    message: str = Field(min_length=5, max_length=5000)

    @model_validator(mode="after")
    def one_item(self):
        if bool(self.booking_id) == bool(self.vm_id):
            raise ValueError("Укажите либо компьютер (booking_id), либо виртуалку (vm_id)")
        return self


def _after_today(value: date) -> date:
    if value <= clock.today():
        raise ValueError("Желаемый срок — не раньше завтрашнего дня")
    return value


class BuildCreate(InputModel):
    """Сборка по запросу: типовая сборка из списка или своя конфигурация — одно из двух."""

    build: str | None = Field(default=None, max_length=300)
    custom: str | None = Field(default=None, max_length=2000)
    os_label: str = Field(min_length=2, max_length=64)
    department_id: int | None = None  # админ может указать любой отдел, остальным — свой
    requester_name: str = Field(min_length=2, max_length=255)
    requester_nick: str = Field(min_length=1, max_length=128)
    purpose: str | None = Field(default=None, max_length=2000)
    expected_return_at: ReturnDate
    wanted_by: Annotated[date, AfterValidator(_after_today)] | None = None  # к какому дню нужен ПК (необязательно)

    @model_validator(mode="after")
    def one_variant(self):
        if bool(self.build) == bool(self.custom):
            raise ValueError("Выберите типовую сборку или опишите свою конфигурацию — одно из двух")
        if self.custom and len(self.custom) < 5:
            raise ValueError("Опишите конфигурацию подробнее")
        return self


class OrderOptions(BaseModel):
    """Что можно выбрать при заказе физического ПК (Админка → «Настройки»)."""

    os: list[str]
    builds: list[str]


class RequestOut(ORMModel):
    id: int
    kind: str
    booking_id: int | None
    vm_id: int | None
    department_id: int | None
    issue_key: str | None
    summary: str
    status: str | None
    status_category: str | None
    error: str | None
    created_at: datetime
    url: str | None = None


class CommentOut(BaseModel):
    author: str
    body: str
    created: str | None
    from_portal: bool


class RequestDetail(BaseModel):
    request: RequestOut
    comments: list[CommentOut]


class CommentIn(InputModel):
    message: str = Field(min_length=1, max_length=5000)
