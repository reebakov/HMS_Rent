"""Общие фикстуры. Нужен реальный PostgreSQL (FOR UPDATE, JSONB, partial unique index): см. docker-compose.test.yml.

Настройки приложения читаются при импорте, поэтому DATABASE_URL выставляется до любого `import app`.
"""
import functools
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://hmsrent:hmsrent@localhost:5432/hmsrent_test"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-32b")
os.environ.setdefault("MATTERMOST_WEBHOOK_URL", "")

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_session_token, hash_password  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import Computer, ComputerStatus, Department, Pool, User, UserRole  # noqa: E402
from app.services import runtime  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


@functools.cache
def _password_hash(password: str) -> str:
    """scrypt стоит десятки миллисекунд, а тестовых пользователей тысячи: хэш одного и того же пароля считается один раз."""
    return hash_password(password)


@pytest.fixture(scope="session", autouse=True)
def _migrated_db():
    """Один раз за сессию: чистая схема через настоящие миграции (заодно проверяет, что они применяются)."""
    env = os.environ.copy()
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=BACKEND_DIR, env=env, check=False,
                   capture_output=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db(_migrated_db):
    """Перед каждым тестом: пустые таблицы и счётчики, свежий кэш runtime-настроек.

    TRUNCATE дорог, поэтому чистятся только таблицы, в которые писали: в них есть строки или продвинулась их
    последовательность id (строки могли успеть удалить). В большинстве тестов это несколько таблиц из ~16.
    """
    async with engine.begin() as conn:
        tables = (await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        ))).scalars().all()
        used_sequences = set((await conn.execute(text(
            "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' AND last_value IS NOT NULL"
        ))).scalars().all())
        with_rows = (await conn.execute(text(
            " UNION ALL ".join(f"SELECT '{t}' WHERE EXISTS (SELECT 1 FROM \"{t}\")" for t in tables)
        ))).scalars().all() if tables else []
        dirty = [t for t in tables if t in with_rows or f"{t}_id_seq" in used_sequences]
        if dirty:
            await conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in dirty) + " RESTART IDENTITY CASCADE"))
        if "rental_order_seq" in used_sequences:
            await conn.execute(text("ALTER SEQUENCE rental_order_seq RESTART WITH 1"))
    runtime._cache = (0.0, runtime._defaults())
    yield


@pytest_asyncio.fixture
async def session():
    async with SessionLocal() as s:
        yield s


# ---------- Фабрики (каждая коммитит и возвращает объект) ----------

@pytest_asyncio.fixture
async def make_department(session):
    async def _make(name: str = "QA", **kw) -> Department:
        obj = Department(name=name, **kw)
        session.add(obj)
        await session.commit()
        return obj
    return _make


@pytest_asyncio.fixture
async def make_user(session):
    async def _make(username: str = "ivanov", role: str = UserRole.user.value, auth_source: str = "local",
                    department: Department | None = None, password: str | None = "pass12345", **kw) -> User:
        obj = User(username=username, display_name=kw.pop("display_name", username), role=role,
                   auth_source=auth_source, department_id=department.id if department else None,
                   password_hash=_password_hash(password) if password else None, **kw)
        session.add(obj)
        await session.commit()
        return obj
    return _make


@pytest_asyncio.fixture
async def make_pool(session):
    async def _make(name: str = "Main", departments: list[Department] | None = None, is_published: bool = True,
                    **kw) -> Pool:
        obj = Pool(name=name, is_published=is_published, **kw)
        obj.departments = departments or []
        session.add(obj)
        await session.commit()
        return obj
    return _make


@pytest_asyncio.fixture
async def make_computer(session):
    counter = {"n": 0}

    async def _make(name: str | None = None, pool: Pool | None = None, status: str = ComputerStatus.available.value,
                    **kw) -> Computer:
        counter["n"] += 1
        obj = Computer(name=name or f"A{counter['n']:03d}", status=status, pool_id=pool.id if pool else None, **kw)
        session.add(obj)
        await session.commit()
        return obj
    return _make


# ---------- HTTP ----------

@pytest_asyncio.fixture
async def client():
    """Анонимный клиент. Lifespan не запускается (bootstrap не нужен), БД — тестовая."""
    from app.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def login(client):
    """login(user) — ставит клиенту сессионную cookie этого пользователя и возвращает клиента."""
    def _login(user: User) -> httpx.AsyncClient:
        client.cookies.set(settings.cookie_name, create_session_token(user.id, user.username, user.role))
        return client
    return _login


@pytest.fixture
def api():
    """Префикс API: api('/catalog/computers') -> '/api/v1/catalog/computers'."""
    return lambda path: settings.api_prefix + path
