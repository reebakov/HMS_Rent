from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.models import Computer, Department, Tier
from app.schemas.computer import ComputerDetail, ComputerOut, TierSummary
from app.schemas.department import DepartmentOut
from app.services import catalog, departments

router = APIRouter(tags=["catalog"])


@router.get("/catalog/summary", response_model=list[TierSummary])
async def catalog_summary(user: CurrentUser, session: DB) -> list[TierSummary]:
    return await catalog.tier_summary(session, user)


@router.get("/computers", response_model=list[ComputerOut])
async def list_computers(
    user: CurrentUser,
    session: DB,
    tier: Tier | None = None,
    q: str | None = None,
    min_ram: int | None = None,
    gpu_only: bool = False,
    only_available: bool = True,
    sort: catalog.Sort = "name",
) -> list[Computer]:
    return await catalog.list_computers(
        session, user, tier=tier, q=q, min_ram=min_ram, gpu_only=gpu_only, only_available=only_available, sort=sort
    )


@router.get("/computers/{computer_id}", response_model=ComputerDetail)
async def get_computer(computer_id: int, user: CurrentUser, session: DB) -> ComputerDetail:
    return await catalog.get_computer(session, user, computer_id)


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(_: CurrentUser, session: DB) -> list[Department]:
    return await departments.list_active(session)
