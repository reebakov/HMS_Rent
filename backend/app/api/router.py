from fastapi import APIRouter

from app.api.routes import (
    admin,
    admin_extra,
    admin_ops,
    auth,
    bookings,
    catalog,
    executor,
    notifications,
    requests,
    vms,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(bookings.router)
api_router.include_router(admin.router)
api_router.include_router(admin_extra.router)
api_router.include_router(admin_ops.router)
api_router.include_router(vms.router)
api_router.include_router(requests.router)
api_router.include_router(notifications.router)
api_router.include_router(executor.router)
