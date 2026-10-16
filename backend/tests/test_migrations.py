"""Миграции Alembic: цепочка upgrade/downgrade и соответствие моделей схеме.

Тесты гоняют alembic подпроцессом (как conftest) на той же тестовой БД и ВСЕГДА возвращают схему в head.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

import app.models  # noqa: F401 — регистрирует таблицы в metadata
from app.db.base import Base
from app.db.session import engine

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


async def test_models_match_migrations():
    def diff(sync_conn):
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})  # те же опции, что в alembic/env.py
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        result = await conn.run_sync(diff)
    assert result == [], f"модели расходятся с миграциями: {result}"
