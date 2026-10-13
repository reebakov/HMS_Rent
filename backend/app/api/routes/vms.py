from fastapi import APIRouter, status

from app.api.deps import DB, AdminUser, CurrentUser
from app.models import VirtualMachine
from app.schemas.vm import VmCreate, VmOptions, VmOut
from app.services import vms as service

router = APIRouter(tags=["vms"])


@router.get("/vms/options", response_model=VmOptions)
async def vm_options(user: CurrentUser, session: DB) -> VmOptions:
    return await service.options(session, user)


@router.post("/vms", response_model=VmOut, status_code=status.HTTP_201_CREATED)
async def create_vm(data: VmCreate, user: CurrentUser, session: DB) -> VirtualMachine:
    return await service.create_request(session, user, data)


@router.get("/vms/my", response_model=list[VmOut])
async def my_vms(user: CurrentUser, session: DB) -> list[VirtualMachine]:
    return await service.list_vms(session, user)


@router.post("/vms/{vm_id}/release", response_model=VmOut)
async def release_vm(vm_id: int, user: CurrentUser, session: DB) -> VirtualMachine:
    return await service.release(session, user, vm_id)


@router.get("/admin/vms", response_model=list[VmOut])
async def all_vms(_: AdminUser, session: DB, include_deleted: bool = False) -> list[VirtualMachine]:
    return await service.list_vms(session, include_deleted=include_deleted)
