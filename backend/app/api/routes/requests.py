from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.integrations import servicedesk as sd
from app.models import ServiceRequest
from app.schemas.common import InputModel, ORMModel
from app.services import service_requests as service

router = APIRouter(prefix="/requests", tags=["service-desk"])


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


def _out(req: ServiceRequest) -> RequestOut:
    row = RequestOut.model_validate(req)
    row.url = sd.portal_url(req.issue_key) if req.issue_key else None
    return row


@router.get("/config")
async def requests_config(_: CurrentUser) -> dict:
    return {"enabled": settings.service_desk_configured}


@router.get("/my", response_model=list[RequestOut])
async def my_requests(user: CurrentUser, session: DB) -> list[RequestOut]:
    return [_out(r) for r in await service.list_for_user(session, user)]


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(data: RequestCreate, user: CurrentUser, session: DB) -> RequestOut:
    req = await service.create_problem(session, user, booking_id=data.booking_id, vm_id=data.vm_id,
                                       message=data.message)
    return _out(req)


@router.get("/{request_id}", response_model=RequestDetail)
async def request_detail(request_id: int, user: CurrentUser, session: DB) -> RequestDetail:
    req, comments = await service.get_with_comments(session, user, request_id)
    return RequestDetail(request=_out(req), comments=[CommentOut(**c.__dict__) for c in comments])


@router.post("/{request_id}/comments", status_code=status.HTTP_204_NO_CONTENT)
async def add_comment(request_id: int, data: CommentIn, user: CurrentUser, session: DB) -> None:
    await service.add_comment(session, user, request_id, data.message)
