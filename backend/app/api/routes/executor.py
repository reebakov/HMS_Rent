from fastapi import APIRouter, BackgroundTasks, status

from app.api.deps import DB, ExecutorUser
from app.models import ServiceRequestKind
from app.schemas.booking import (
    FAULTY_REASON,
    ExecutorBuildIssue,
    ExecutorBuildOut,
    ExecutorBuildReject,
    ExecutorDiagnosticOut,
    ExecutorOrderOut,
    ExecutorProblemOut,
    ExecutorReject,
    ExecutorReplace,
    ExecutorResult,
    PoolShort,
    ProblemTransitionIn,
    ProblemTransitionOut,
    ReplacementOut,
)
from app.schemas.vm import ExecutorVmOut, ExecutorVmReject
from app.services import builds
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
        tasks.add_task(service.send_diagnose_request, booking.computer_id, user.id)
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


@router.get("/orders/{booking_id}/replacements", response_model=list[ReplacementOut])
async def list_replacements(booking_id: int, _: ExecutorUser, session: DB) -> list[ReplacementOut]:
    """Свободные ПК той же категории, на которые можно заменить неисправный в заказе."""
    return await service.list_replacements(session, booking_id)


@router.post("/orders/{booking_id}/replace", response_model=ExecutorOrderOut)
async def replace_computer(
    booking_id: int, data: ExecutorReplace, user: ExecutorUser, session: DB, tasks: BackgroundTasks
) -> ExecutorOrderOut:
    """Заменить неисправный ПК в заказе другим: заказ тот же, неисправный уходит на диагностику."""
    old_computer_id = (await get_booking(session, booking_id)).computer_id
    booking = await service.replace_computer(session, user, booking_id, data)
    tasks.add_task(push_to_insight)
    tasks.add_task(service.send_diagnose_request, old_computer_id, user.id)
    tasks.add_task(service.rename_prepare_task, booking.id)
    return await service.order_out(session, booking)


@router.get("/builds", response_model=list[ExecutorBuildOut])
async def list_builds(_: ExecutorUser, session: DB) -> list[ExecutorBuildOut]:
    """Заказы на сборку ПК, ждущие выдачи."""
    return await builds.list_builds(session)


@router.get("/pools", response_model=list[PoolShort])
async def list_pools(_: ExecutorUser, session: DB) -> list[PoolShort]:
    """Опубликованные пулы: в какой пул попадёт собранный ПК."""
    return await builds.list_pools(session)


@router.post("/builds/{request_id}/issue", response_model=ExecutorOrderOut)
async def issue_build(
    request_id: int, data: ExecutorBuildIssue, user: ExecutorUser, session: DB, tasks: BackgroundTasks
) -> ExecutorOrderOut:
    """Выдать собранный ПК заказчику: бронь, данные подключения, пул."""
    booking = await builds.issue(session, user, request_id, data)
    tasks.add_task(push_to_insight)
    return await service.order_out(session, await get_booking(session, booking.id))


@router.post("/builds/{request_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_build(request_id: int, data: ExecutorBuildReject, user: ExecutorUser, session: DB) -> None:
    await builds.reject(session, user, request_id, data.reason, data.comment)


@router.get("/vms", response_model=list[ExecutorVmOut])
async def list_vm_checks(_: ExecutorUser, session: DB) -> list[ExecutorVmOut]:
    """ВМ, созданные и ждущие проверки исполнителем."""
    return await service.list_vm_checks(session)


@router.post("/vms/{vm_id}/confirm", response_model=ExecutorVmOut)
async def confirm_vm(vm_id: int, user: ExecutorUser, session: DB) -> ExecutorVmOut:
    return (await service.vms_out(session, [await service.confirm_vm(session, user, vm_id)]))[0]


@router.post("/vms/{vm_id}/recreate", response_model=ExecutorVmOut)
async def recreate_vm(vm_id: int, _: ExecutorUser, session: DB) -> ExecutorVmOut:
    return (await service.vms_out(session, [await service.recreate_vm(session, vm_id)]))[0]


@router.post("/vms/{vm_id}/reject", response_model=ExecutorVmOut)
async def reject_vm(vm_id: int, data: ExecutorVmReject, user: ExecutorUser, session: DB) -> ExecutorVmOut:
    return (await service.vms_out(session, [await service.reject_vm(session, user, vm_id, data.reason, data.comment)]))[0]


@router.get("/diagnostics", response_model=list[ExecutorDiagnosticOut])
async def list_diagnostics(_: ExecutorUser, session: DB) -> list[ExecutorDiagnosticOut]:
    """ПК на диагностике (выведены из пула как неисправные)."""
    return await service.list_diagnostics(session)


@router.post("/diagnostics/{request_id}/repaired", response_model=ExecutorDiagnosticOut)
async def repair_computer(request_id: int, user: ExecutorUser, session: DB, tasks: BackgroundTasks) -> ExecutorDiagnosticOut:
    """Диагностика закончена: ПК возвращается в прежний пул и становится свободным."""
    out = await service.repair_computer(session, user, request_id)
    tasks.add_task(push_to_insight)
    return out


@router.get("/returns", response_model=list[ExecutorOrderOut])
async def list_returns(_: ExecutorUser, session: DB) -> list[ExecutorOrderOut]:
    """Вернувшиеся ПК, ждущие очистки диска (со ссылкой на заявку «Возврат ПК»)."""
    return await service.orders_out(session, await service.list_returns(session), ServiceRequestKind.return_)


@router.post("/returns/{booking_id}/cleaned", response_model=ExecutorOrderOut)
async def confirm_cleaned(booking_id: int, user: ExecutorUser, session: DB, tasks: BackgroundTasks) -> ExecutorOrderOut:
    booking = await service.confirm_cleaned(session, user, booking_id)
    tasks.add_task(push_to_insight)
    return await service.order_out(session, booking, ServiceRequestKind.return_)
