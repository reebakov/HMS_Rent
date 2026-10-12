"""Синхронизация Insight -> локальная БД.

Правила:
* Insight — источник правды по «железу» и его статусу (свободен / ремонт / списан ...).
* Портал — источник правды по бронированиям. Если у ПК есть активная бронь, его статус — booked.
* Пропавшие из Insight ПК не удаляются, а архивируются: история должна сохраниться.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.insight.factory import create_insight_source
from app.integrations.insight.mapping import map_object
from app.models import Booking, BookingStatus, Computer, ComputerStatus, EventType, SyncRun
from app.services.events import add_event
from app.services.tiering import classify

log = logging.getLogger(__name__)

SYNC_LOCK_KEY = 73010001  # ключ advisory-lock: одновременно идёт только одна синхронизация

TRACKED = (
    "name", "hostname", "is_virtual", "cpu", "cpu_cores", "ram_gb", "storage", "storage_gb",
    "gpu", "os", "location", "serial_number", "ip_address", "insight_status",
)


async def run_sync(session: AsyncSession) -> SyncRun | None:
    started = datetime.now(timezone.utc)
    source = create_insight_source()
    limit = settings.insight_max_objects
    try:
        objects = await source.fetch_objects(limit=limit)
        mapping = source.mapping
    except Exception as exc:  # noqa: BLE001 — любую ошибку Insight пишем в журнал синхронизаций
        log.exception("Ошибка чтения Insight")
        return await _save_failed(session, source.mode, str(exc))
    finally:
        await source.close()

    try:
        locked = await session.scalar(select(func.pg_try_advisory_xact_lock(SYNC_LOCK_KEY)))
        if not locked:
            log.info("Синхронизация уже идёт в другом процессе — пропускаю")
            return None

        computers = (await session.scalars(select(Computer))).unique().all()
        by_insight_id = {c.insight_object_id: c for c in computers if c.insight_object_id is not None}
        if not objects and by_insight_id:
            raise RuntimeError("Insight вернул 0 объектов — проверьте query в insight_mapping.yaml")
        initial_import = not by_insight_id  # первый импорт: не засоряем журнал тысячами «ПК появился»
        partial = bool(limit) and len(objects) >= limit  # пробный прогон: архивировать нельзя

        booked_ids = set(
            await session.scalars(select(Booking.computer_id).where(Booking.status == BookingStatus.active))
        )
        now = datetime.now(timezone.utc)
        run = SyncRun(
            mode=source.mode, status="success", started_at=started,
            total=len(objects), created=0, updated=0, archived=0,
        )
        new_computers: list[Computer] = []
        seen: set[int] = set()

        for obj in objects:
            data = map_object(obj, mapping)
            seen.add(obj.id)
            comp = by_insight_id.get(obj.id)
            is_new = comp is None
            if comp is None:
                comp = Computer(insight_object_id=obj.id, name=data.name, attributes={})
                session.add(comp)
                new_computers.append(comp)
                old_status = None
            else:
                old_status = comp.insight_status

            changed = False
            for field in TRACKED:
                value = getattr(data, field)
                if getattr(comp, field) != value:
                    setattr(comp, field, value)
                    changed = True
            if comp.attributes != obj.attributes:
                comp.attributes = obj.attributes
                changed = True

            comp.insight_key = obj.key
            comp.insight_object_type = obj.object_type
            comp.insight_object_type_id = obj.object_type_id
            comp.tier = comp.tier_override or data.tier or classify(
                is_virtual=data.is_virtual, ram_gb=data.ram_gb, gpu=data.gpu
            )
            comp.status = (
                ComputerStatus.booked.value
                if comp.id in booked_ids
                # пока изменения портала не доехали до Insight, статус Insight устаревший — не трогаем
                else comp.status if comp.writeback_pending
                else data.status
            )
            comp.synced_at = now
            if comp.is_archived:
                comp.is_archived = False
                changed = True

            if not is_new:
                run.updated += int(changed)
                if old_status != data.insight_status:
                    add_event(
                        session,
                        computer_id=comp.id,
                        event_type=EventType.insight_status_changed,
                        from_status=old_status,
                        to_status=data.insight_status,
                        message=f"Статус в Insight: {old_status or '—'} → {data.insight_status or '—'}",
                    )

        for comp in by_insight_id.values():
            if not partial and comp.insight_object_id not in seen and not comp.is_archived:
                comp.is_archived = True
                run.archived += 1
                add_event(
                    session,
                    computer_id=comp.id,
                    event_type=EventType.insight_removed,
                    message="Объект больше не находится в Insight (по запросу из маппинга)",
                )

        await session.flush()  # получить id у новых ПК
        for comp in [] if initial_import else new_computers:
            add_event(
                session,
                computer_id=comp.id,
                event_type=EventType.insight_created,
                to_status=comp.insight_status,
                message="ПК появился в Insight",
            )
        run.created = len(new_computers)
        run.finished_at = datetime.now(timezone.utc)
        if partial:
            run.error = f"Пробная синхронизация: загружены первые {limit} объектов (INSIGHT_MAX_OBJECTS)"
        session.add(run)
        await session.commit()
        log.info("Синхронизация: всего %s, новых %s, изменено %s, в архив %s",
                 run.total, run.created, run.updated, run.archived)
        return run
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        log.exception("Ошибка синхронизации")
        return await _save_failed(session, source.mode, str(exc))


async def _save_failed(session: AsyncSession, mode: str, error: str) -> SyncRun:
    now = datetime.now(timezone.utc)
    run = SyncRun(mode=mode, status="failed", error=error[:2000], started_at=now, finished_at=now)
    session.add(run)
    await session.commit()
    return run
