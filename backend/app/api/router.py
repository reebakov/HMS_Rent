from fastapi import APIRouter

from app.api.routes import admin, admin_extra, auth, bookings, catalog, vms

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(bookings.router)
api_router.include_router(admin.router)
api_router.include_router(admin_extra.router)
api_router.include_router(vms.router)
