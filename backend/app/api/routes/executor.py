from fastapi import APIRouter, BackgroundTasks

from app.api.deps import DB, ExecutorUser
from app.models import ServiceRequestKind
from app.schemas.booking import (
    FAULTY_REASON,
    ExecutorOrderOut,
    ExecutorProblemOut,
    ExecutorReject,
    ExecutorResult,
    ProblemTransitionIn,
    ProblemTransitionOut,
)
from app.services import executor as service
from app.services.bookings import get_booking, push_to_insight

router = APIRouter(prefix="/executor", tags=["executor"])


@router.get("/orders", response_model=list[ExecutorOrderOut])
async def list_orders(_: ExecutorUser, session: DB) -> list[ExecutorOrderOut]:
    return await service.orders_out(session, await service.list_orders(session))


@router.get("/orders/{booking_id}", response_model=ExecutorOrderOut)
async def get_order(booking_id: int, _: ExecutorUser, session: DB) -> ExecutorOrderOut:
    return await service.order_out(session, await get_booking(session, booking_id))


@router.post("/orders/{booking_id}/result", response_model=ExecutorOrderOut)
async def save_result(booking_id: int, data: ExecutorResult, user: ExecutorUser, session: DB) -> ExecutorOrderOut:
    return await service.order_out(session, await service.save_result(session, user, booking_id, data))


@router.post("/orders/{booking_id}/reject", response_model=ExecutorOrderOut)
async def reject_order(
    booking_id: int, data: ExecutorReject, user: ExecutorUser, session: DB, tasks: BackgroundTasks
) -> ExecutorOrderOut:
    booking = await service.reject_order(session, user, booking_id, data)
    tasks.add_task(push_to_insight)
    if data.reason == FAULTY_REASON:
        tasks.add_task(service.create_diagnose_request, booking.id, user.id, data.comment)
    return await service.order_out(session, booking)


@router.get("/problems", response_model=list[ExecutorProblemOut])
async def list_problems(_: ExecutorUser, session: DB) -> list[ExecutorProblemOut]:
    """Проблемы по заказам: заявки «Сообщить о проблеме» от заказчиков, открытые выше."""
    return await service.list_problems(session)


@router.get("/problems/{request_id}/transitions", response_model=list[ProblemTransitionOut])
async def problem_transitions(request_id: int, _: ExecutorUser, session: DB) -> list[ProblemTransitionOut]:
    """Куда можно перевести задачу Jira по проблеме из её текущего статуса."""
    return await service.problem_transitions(session, request_id)


@router.post("/problems/{request_id}/transition", response_model=ExecutorProblemOut)
async def move_problem(request_id: int, data: ProblemTransitionIn, _: ExecutorUser, session: DB) -> ExecutorProblemOut:
    return await service.move_problem(session, request_id, data.transition_id)


@router.get("/returns", response_model=list[ExecutorOrderOut])
async def list_returns(_: ExecutorUser, session: DB) -> list[ExecutorOrderOut]:
    """Вернувшиеся ПК, ждущие очистки диска (со ссылкой на заявку «Возврат ПК»)."""
    return await service.orders_out(session, await service.list_returns(session), ServiceRequestKind.return_)


@router.post("/returns/{booking_id}/cleaned", response_model=ExecutorOrderOut)
async def confirm_cleaned(booking_id: int, user: ExecutorUser, session: DB, tasks: BackgroundTasks) -> ExecutorOrderOut:
    booking = await service.confirm_cleaned(session, user, booking_id)
    tasks.add_task(push_to_insight)
    return await service.order_out(session, booking, ServiceRequestKind.return_)
