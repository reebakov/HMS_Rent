from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import InputModel, ORMModel


class RequestCreate(InputModel):
    booking_id: int | None = None
    vm_id: int | None = None
    message: str = Field(min_length=5, max_length=5000)

    @model_validator(mode="after")
    def one_item(self):
        if bool(self.booking_id) == bool(self.vm_id):
            raise ValueError("Укажите либо компьютер (booking_id), либо виртуалку (vm_id)")
        return self


class RequestOut(ORMModel):
    id: int
    kind: str
    booking_id: int | None
    vm_id: int | None
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
