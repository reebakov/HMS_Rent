"""Общие помощники сервисов: конфликт по уникальному индексу, отделы, запись настроек."""
import pytest
from sqlalchemy import func, select

from app.core.errors import Conflict, NotFound
from app.db.integrity import conflict_on_integrity_error
from app.models import AppSetting, Department
from app.services import departments, runtime


async def test_integrity_error_becomes_conflict_and_session_stays_usable(session, make_department):
    await make_department("QA")
    session.add(Department(name="QA"))
    with pytest.raises(Conflict, match="уже есть"):
        async with conflict_on_integrity_error(session, "Отдел уже есть"):
            await session.commit()
    assert await session.scalar(select(func.count()).select_from(Department)) == 1  # после rollback сессия рабочая


async def test_block_without_error_passes_through(session):
    async with conflict_on_integrity_error(session, "не нужен"):
        session.add(Department(name="Ops"))
        await session.commit()
    assert await session.scalar(select(func.count()).select_from(Department)) == 1


async def test_other_errors_are_not_swallowed(session):
    with pytest.raises(ZeroDivisionError):
        async with conflict_on_integrity_error(session, "не нужен"):
            _ = 1 / 0


async def test_get_active_department(session, make_department):
    qa = await make_department("QA")
    off = await make_department("Old", is_active=False)
    assert (await departments.get_active(session, qa.id)).id == qa.id
    for missing in (off.id, 9999):
        with pytest.raises(NotFound, match="Отдел не найден"):
            await departments.get_active(session, missing)


async def test_get_department_ignores_activity_but_not_existence(session, make_department):
    off = await make_department("Old", is_active=False)
    assert (await departments.get(session, off.id)).id == off.id
    with pytest.raises(NotFound, match="Отдел не найден"):
        await departments.get(session, 9999)


async def test_get_many_departments_requires_all(session, make_department):
    a, b = await make_department("A"), await make_department("B")
    assert {d.id for d in await departments.get_many(session, [a.id, b.id, a.id])} == {a.id, b.id}
    assert await departments.get_many(session, []) == []
    with pytest.raises(NotFound, match="Один из отделов не найден"):
        await departments.get_many(session, [a.id, 9999])


async def test_put_setting_creates_then_updates(session):
    await runtime.put_setting(session, "some_key", "v1")
    await session.commit()
    await runtime.put_setting(session, "some_key", "v2")
    await session.commit()
    rows = (await session.scalars(select(AppSetting).where(AppSetting.key == "some_key"))).all()
    assert [r.value for r in rows] == ["v2"]
