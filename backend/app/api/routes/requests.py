from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.schemas.service_request import CommentIn, CommentOut, RequestCreate, RequestDetail, RequestOut
from app.services import service_requests as service

router = APIRouter(prefix="/requests", tags=["service-desk"])


@router.get("/config")
async def requests_config(_: CurrentUser) -> dict:
    return {"enabled": settings.service_desk_configured}


@router.get("/my", response_model=list[RequestOut])
async def my_requests(user: CurrentUser, session: DB) -> list[RequestOut]:
    return [service.request_out(r) for r in await service.list_for_user(session, user)]


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(data: RequestCreate, user: CurrentUser, session: DB) -> RequestOut:
    req = await service.create_problem(session, user, booking_id=data.booking_id, vm_id=data.vm_id,
                                       message=data.message)
    return service.request_out(req)


@router.get("/{request_id}", response_model=RequestDetail)
async def request_detail(request_id: int, user: CurrentUser, session: DB) -> RequestDetail:
    req, comments = await service.get_with_comments(session, user, request_id)
    return RequestDetail(request=service.request_out(req), comments=[CommentOut(**c.__dict__) for c in comments])


@router.post("/{request_id}/comments", status_code=status.HTTP_204_NO_CONTENT)
async def add_comment(request_id: int, data: CommentIn, user: CurrentUser, session: DB) -> None:
    await service.add_comment(session, user, request_id, data.message)
