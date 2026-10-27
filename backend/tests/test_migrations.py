"""Миграции Alembic: цепочка upgrade/downgrade и соответствие моделей схеме.

Тесты гоняют alembic подпроцессом (как conftest) на той же тестовой БД и ВСЕГДА возвращают схему в head.
"""
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401 — регистрирует таблицы в metadata
from app.db.base import Base
from app.db.session import engine
from app.models import BookingExtension
from tests.sync_fakes import add_booking
from tests.test_overdue import add_vm

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=os.environ.copy(),
                          capture_output=True, text=True)


async def _leftovers() -> dict[str, list[str]]:
    """Всё, что осталось в схеме public, кроме alembic_version."""
    q = {
        "tables": "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'",
        "sequences": "SELECT sequencename FROM pg_sequences WHERE schemaname='public'",
        "enums": "SELECT typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                 "WHERE n.nspname='public' AND t.typtype='e'",
    }
    async with engine.connect() as conn:
        return {k: sorted((await conn.execute(text(sql))).scalars().all()) for k, sql in q.items()}


def test_single_linear_head():
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert len(script.get_heads()) == 1, "в цепочке миграций несколько голов (нужен merge)"
    revs = list(script.walk_revisions())
    assert all(len(r.nextrev) <= 1 for r in revs)  # нет веток


async def test_upgrade_downgrade_roundtrip():
    try:
        down = _alembic("downgrade", "base")
        assert down.returncode == 0, down.stderr[-2000:]
        assert await _leftovers() == {"tables": [], "sequences": [], "enums": []}, "downgrade base оставил объекты"

        up = _alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr[-2000:]
        down = _alembic("downgrade", "base")
        assert down.returncode == 0, down.stderr[-2000:]
        up = _alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr[-2000:]
    finally:
        _alembic("upgrade", "head")  # схема обязана остаться в head для остальных тестов
        await engine.dispose()  # соединения пула могли закэшировать планы по пересозданным таблицам

    assert "(head)" in _alembic("current").stdout


async def test_upgrade_is_idempotent_at_head():
    """Dockerfile применяет миграции при каждом старте: повторный upgrade head ничего не ломает."""
    assert _alembic("upgrade", "head").returncode == 0


def test_dockerfile_hands_pid1_to_uvicorn():
    """Без exec PID 1 остаётся sh и не передаёт SIGTERM: docker stop ждёт 10 с и убивает backend, выкатка дольше."""
    cmd = next(line for line in (Path(__file__).parents[1] / "Dockerfile").read_text().splitlines() if line.startswith("CMD"))
    assert "alembic upgrade head && exec uvicorn" in cmd


async def test_models_match_migrations():
    def diff(sync_conn):
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})  # те же опции, что в alembic/env.py
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        result = await conn.run_sync(diff)
    assert result == [], f"модели расходятся с миграциями: {result}"


# ---------- 0009: продления ВМ ----------

async def _seed_extensions(session, make_user, make_department, make_computer) -> None:
    """ПК с бронью и ВМ одного отдела; по одному продлению на ПК и на ВМ."""
    dept = await make_department("QA")
    user = await make_user("u", department=dept)
    booking = await add_booking(session, await make_computer("PC-1"), user, dept)
    vm = await add_vm(session, user, dept)
    session.add_all([BookingExtension(booking_id=booking.id, user_id=user.id, new_return_at=date(2026, 7, 1)),
                     BookingExtension(vm_id=vm.id, user_id=user.id, new_return_at=date(2026, 7, 2))])
    await session.commit()


async def _extension_booking_ids() -> list[int | None]:
    async with engine.connect() as conn:
        return list((await conn.execute(text("SELECT booking_id FROM booking_extensions ORDER BY id"))).scalars())


async def test_extension_targets_exactly_one(session, make_user, make_department, make_computer):
    """CHECK в БД: у продления ровно одно из booking_id / vm_id."""
    await _seed_extensions(session, make_user, make_department, make_computer)
    for columns, values in (("user_id, new_return_at", "1, '2026-07-03'"),  # id=1: таблицы очищены с RESTART IDENTITY
                            ("booking_id, vm_id, user_id, new_return_at", "1, 1, 1, '2026-07-03'")):
        with pytest.raises(IntegrityError, match="one_target"):
            await session.execute(text(f"INSERT INTO booking_extensions ({columns}) VALUES ({values})"))
        await session.rollback()


async def test_downgrade_0009_keeps_pc_extensions_and_drops_vm_ones(session, make_user, make_department,
                                                                    make_computer):
    await _seed_extensions(session, make_user, make_department, make_computer)
    assert await _extension_booking_ids() == [1, None]
    try:
        down = _alembic("downgrade", "0008")
        assert down.returncode == 0, down.stderr[-2000:]
        assert await _extension_booking_ids() == [1]  # в старой схеме нет vm_id: остались только продления ПК
        up = _alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr[-2000:]
        assert await _extension_booking_ids() == [1]
    finally:
        _alembic("upgrade", "head")
        await engine.dispose()


# ---------- 0011: ОС виртуалки и срок в Notes ----------

async def test_0011_backfills_os_from_label(session, make_user, make_department):
    """У старых ВМ ОС выводится из названия: без названия и Windows — windows, Ubuntu и др. — linux, прочее — пусто."""
    dept = await make_department("QA")
    user = await make_user("u", department=dept)
    labels = ["Windows 10", None, "Ubuntu 22.04", "Debian 12", "Своя ОС"]
    for i, label in enumerate(labels):
        await add_vm(session, user, dept, name=f"vm-os-{i}", os_label=label)
    try:
        assert _alembic("downgrade", "0010").returncode == 0
        assert _alembic("upgrade", "head").returncode == 0
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT os_label, os FROM virtual_machines ORDER BY id"))).all()
    finally:
        _alembic("upgrade", "head")
        await engine.dispose()
    assert [r.os for r in rows] == ["windows", "windows", "linux", "linux", None]
