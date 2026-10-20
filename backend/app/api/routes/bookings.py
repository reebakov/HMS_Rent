from fastapi import APIRouter, BackgroundTasks, status

from app.api.deps import DB, CurrentUser
from app.models import Booking
from app.schemas.booking import BookingCreate, BookingExtend, BookingOut, BookingReturn
from app.services import bookings as service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(data: BookingCreate, user: CurrentUser, session: DB, tasks: BackgroundTasks) -> Booking:
    booking = await service.create_booking(session, user, data)
    tasks.add_task(service.push_to_insight)
    tasks.add_task(service.create_prepare_request, booking.id, user.id)
    return booking


@router.get("/my", response_model=list[BookingOut])
async def my_bookings(user: CurrentUser, session: DB) -> list[Booking]:
    return await service.list_user_bookings(session, user)


@router.post("/{booking_id}/return", response_model=BookingOut)
async def return_booking(
    booking_id: int, data: BookingReturn, user: CurrentUser, session: DB, tasks: BackgroundTasks
) -> Booking:
    booking = await service.return_booking(session, user, booking_id, data.comment)
    tasks.add_task(service.push_to_insight)
    tasks.add_task(service.create_return_request, booking.id, user.id)
    return booking


@router.post("/{booking_id}/extend", response_model=BookingOut)
async def extend_booking(
    booking_id: int, data: BookingExtend, user: CurrentUser, session: DB, tasks: BackgroundTasks
) -> Booking:
    booking = await service.extend_booking(session, user, booking_id, data)
    tasks.add_task(service.push_to_insight)  # новый «Срок использования» в Insight
    return booking
