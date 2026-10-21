"""Общие подделки для тестов sync / writeback / inventory: фейковый Insight и хелперы данных."""
from datetime import date

from sqlalchemy import select

from app.integrations.insight.base import InsightObject
from app.integrations.insight.factory import get_mapping
from app.models import AssetEvent, Booking, Computer


def insight_obj(oid: int = 1, name: str = "A001", *, status: str | None = "Свободен", otype: str = "Компьютер",
                **attrs: str) -> InsightObject:
    """Объект Insight с именами атрибутов из config/insight_mapping.mock.yaml.

    Дополнительные атрибуты — по русским именам через словарь: insight_obj(1, **{"ОЗУ": "16 GB"}).
    """
    attributes = {"Name": name}
    if status is not None:
        attributes["Статус"] = status
    attributes.update(attrs)
    return InsightObject(id=oid, key=f"ITAM-{oid}", label=name, object_type=otype, object_type_id=21,
                         attributes=attributes)


class FakeInsight:
    """Источник Insight: отдаёт заданные объекты (или бросает ошибку) и запоминает вызовы записи."""

    mode = "mock"

    def __init__(self, objects: list[InsightObject] | None = None, *, fetch_error: Exception | None = None,
                 write_errors: list[Exception | None] | None = None):
        self.objects = objects or []
        self.fetch_error = fetch_error
        self.write_errors = list(write_errors or [])  # по одному на каждый вызов update_object; None — успех
        self.mapping = get_mapping()
        self.calls: list[dict] = []
        self.closed = False
        self.on_write = None  # async-хук: что происходит в портале, пока идёт запись в Insight

    async def fetch_objects(self, limit: int = 0) -> list[InsightObject]:
        if self.fetch_error:
            raise self.fetch_error
        return self.objects[:limit] if limit else list(self.objects)

    async def update_object(self, object_id, object_type_id, values, optional=None) -> None:
        self.calls.append({"id": object_id, "type_id": object_type_id, "values": dict(values),
                           "optional": set(optional or ())})
        if self.on_write:
            await self.on_write()
        if self.write_errors:
            err = self.write_errors.pop(0)
            if err:
                raise err

    async def close(self) -> None:
        self.closed = True


def patch_source(monkeypatch, fake: FakeInsight, *modules: str) -> FakeInsight:
    """Подменяет create_insight_source в указанных модулях приложения (sync / writeback)."""
    for mod in modules:
        monkeypatch.setattr(f"app.services.{mod}.create_insight_source", lambda: fake)
    return fake


async def reload_computers(session) -> dict[str, Computer]:
    """Все ПК из БД (минуя кэш сессии), по имени."""
    rows = (await session.scalars(select(Computer).execution_options(populate_existing=True))).unique().all()
    return {c.name: c for c in rows}


async def events_of(session, computer: Computer, event_type: str | None = None) -> list[AssetEvent]:
    stmt = select(AssetEvent).where(AssetEvent.computer_id == computer.id).order_by(AssetEvent.id)
    if event_type:
        stmt = stmt.where(AssetEvent.event_type == event_type)
    return list((await session.scalars(stmt)).unique().all())


_order = {"n": 0}


async def add_booking(session, computer: Computer, user, department, *, expected_return_at: date | None = None,
                      status: str = "active", requester_name: str = "Иван Иванов", requester_nick: str = "ivan",
                      **kw) -> Booking:
    """Бронь напрямую в БД (в обход сервиса), чтобы тесты sync/inventory не зависели от bookings.py."""
    _order["n"] += 1
    b = Booking(computer_id=computer.id, department_id=department.id, user_id=user.id,
                order_number=1000 + _order["n"], requester_name=requester_name, requester_nick=requester_nick,
                status=status, expected_return_at=expected_return_at, **kw)
    session.add(b)
    await session.commit()
    return b
