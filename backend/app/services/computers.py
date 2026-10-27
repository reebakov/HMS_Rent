"""Карточка ПК в админке: история и правки админа."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.models import Booking, BookingStatus, Computer, EventType, User
from app.schemas.admin import ComputerAdminUpdate, ComputerHistoryOut, EventOut, InventoryRow
from app.schemas.booking import BookingOut
from app.services import inventory
from app.services.events import add_event
from app.services.tiering import classify


async def _get(session: AsyncSession, computer_id: int) -> Computer:
    comp = await session.get(Computer, computer_id)
    if comp is None:
        raise NotFound("Компьютер не найден")
    return comp


async def get_history(session: AsyncSession, computer_id: int) -> ComputerHistoryOut:
    comp = await _get(session, computer_id)
    bookings = (await session.scalars(
        select(Booking).where(Booking.computer_id == comp.id).order_by(Booking.booked_at.desc())
    )).unique().all()
    active = next((b for b in bookings if b.status == BookingStatus.active), None)
    events, _ = await inventory.list_events(session, computer_id=comp.id, limit=200)
    return ComputerHistoryOut(
        computer=inventory.inventory_row(comp, active),
        attributes=comp.attributes or {},
        bookings=[BookingOut.model_validate(b) for b in bookings],
        events=[EventOut.model_validate(e) for e in events],
    )


async def update(session: AsyncSession, admin: User, computer_id: int, data: ComputerAdminUpdate) -> InventoryRow:
    comp = await _get(session, computer_id)
    changes = data.model_dump(exclude_unset=True)
    if "tier_override" in changes:
        comp.tier_override = changes["tier_override"].value if changes["tier_override"] else None
        comp.tier = comp.tier_override or classify(is_virtual=comp.is_virtual, ram_gb=comp.ram_gb, gpu=comp.gpu)
    if "note" in changes:
        comp.note = changes["note"] or None
    add_event(
        session, computer_id=comp.id, actor_id=admin.id, event_type=EventType.admin_update,
        message="Изменено админом: " + ", ".join(changes) if changes else "Без изменений",
        payload={k: str(v) for k, v in changes.items()},
    )
    await session.commit()
    await session.refresh(comp)
    active = await session.scalar(
        select(Booking).where(Booking.computer_id == comp.id, Booking.status == BookingStatus.active)
    )
    return inventory.inventory_row(comp, active)
