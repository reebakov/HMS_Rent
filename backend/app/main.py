import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import DomainError
from app.db.session import SessionLocal
from app.services.bootstrap import bootstrap

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hmsrent")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment == "prod" and settings.auth_dev_enabled:
        raise RuntimeError("AUTH_DEV_ENABLED=true запрещён в prod")
    if settings.environment == "prod" and settings.secret_key.startswith("change-me"):
        raise RuntimeError("Задайте SECRET_KEY в .env")
    if not settings.bouncer_enabled:
        log.warning("Вход через Bouncer выключен: не заданы BOUNCER_AUTHORIZE_URL / BOUNCER_TOKEN_URL / BOUNCER_CLIENT_ID")
    async with SessionLocal() as session:
        await bootstrap(session)
    log.info("%s запущен: bouncer=%s, local=%s, dev=%s, insight=%s", settings.app_name, settings.bouncer_enabled,
             settings.auth_local_enabled, settings.auth_dev_enabled, settings.insight_mode)
    yield


app = FastAPI(title=f"{settings.app_name} API", version=settings.app_version, lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/api/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "version": settings.app_version}


app.include_router(api_router, prefix=settings.api_prefix)