from fastapi import APIRouter, BackgroundTasks

from app.api.deps import DB, ExecutorUser
from app.models import Booking
from app.schemas.booking import FAULTY_REASON, ExecutorOrderOut, ExecutorReject, ExecutorResult
from app.services import executor as service
from app.services.bookings import get_booking, push_to_insight

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


@router.post("/orders/{booking_id}/reject", response_model=ExecutorOrderOut)
async def reject_order(
    booking_id: int, data: ExecutorReject, user: ExecutorUser, session: DB, tasks: BackgroundTasks
) -> Booking:
    booking = await service.reject_order(session, user, booking_id, data)
    tasks.add_task(push_to_insight)
    if data.reason == FAULTY_REASON:
        tasks.add_task(service.create_diagnose_request, booking.id, user.id, data.comment)
    return booking
