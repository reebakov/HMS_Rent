from fastapi import APIRouter

from app.api.deps import DB, ExecutorUser
from app.models import Booking
from app.schemas.booking import ExecutorOrderOut, ExecutorResult
from app.services import executor as service
from app.services.bookings import get_booking

router = APIRouter(prefix="/executor", tags=["executor"])


@router.get("/orders", response_model=list[ExecutorOrderOut])
async def list_orders(_: ExecutorUser, session: DB) -> list[Booking]:
    return await service.list_orders(session)


@router.get("/orders/{booking_id}", response_model=ExecutorOrderOut)
async def get_order(booking_id: int, _: ExecutorUser, session: DB) -> Booking:
    return await get_booking(session, booking_id)


@router.post("/orders/{booking_id}/result", response_model=ExecutorOrderOut)
async def save_result(booking_id: int, data: ExecutorResult, user: ExecutorUser, session: DB) -> Booking:
    return await service.save_result(session, user, booking_id, data)
