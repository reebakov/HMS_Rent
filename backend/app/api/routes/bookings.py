from fastapi import APIRouter, BackgroundTasks, status

from app.api.deps import DB, CurrentUser
from app.db.session import SessionLocal
from app.models import Booking, User
from app.schemas.booking import BookingCreate, BookingOut, BookingReturn
from app.services import bookings as service
from app.services import service_requests
from app.services.writeback import push_pending

router = APIRouter(prefix="/bookings", tags=["bookings"])


async def _return_request(booking_id: int, user_id: int) -> None:
    """Заявка «Возврат ПК» в Service Desk — в фоне, чтобы не задерживать возврат."""
    async with SessionLocal() as session:
        actor = await session.get(User, user_id)
        if actor is not None:
            await service_requests.create_return(session, booking_id, actor)


async def _push_to_insight() -> None:
    """Сразу после брони/возврата отправляем статус в Insight, не дожидаясь круга воркера."""
    async with SessionLocal() as session:
        await push_pending(session)


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(data: BookingCreate, user: CurrentUser, session: DB, tasks: BackgroundTasks) -> Booking:
    booking = await service.create_booking(session, user, data)
    tasks.add_task(_push_to_insight)
    return booking


@router.get("/my", response_model=list[BookingOut])
async def my_bookings(user: CurrentUser, session: DB) -> list[Booking]:
    return await service.list_user_bookings(session, user)


@router.post("/{booking_id}/return", response_model=BookingOut)
async def return_booking(
    booking_id: int, data: BookingReturn, user: CurrentUser, session: DB, tasks: BackgroundTasks
) -> Booking:
    booking = await service.return_booking(session, user, booking_id, data.comment)
    tasks.add_task(_push_to_insight)
    tasks.add_task(_return_request, booking.id, user.id)
    return booking
