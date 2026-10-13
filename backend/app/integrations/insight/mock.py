"""Mock-источник: берёт «объекты Insight» из JSON-файла. Нужен, чтобы запустить портал без доступа к Jira."""
import json
import logging
from pathlib import Path

from app.integrations.insight.base import InsightObject
from app.integrations.insight.mapping import InsightMapping

log = logging.getLogger(__name__)


class MockInsightSource:
    mode = "mock"

    def __init__(self, path: Path, mapping: InsightMapping):
        self.path = path
        self.mapping = mapping

    async def fetch_objects(self, limit: int = 0) -> list[InsightObject]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if limit:
            raw = raw[:limit]
        return [
            InsightObject(
                id=item["id"],
                key=item["key"],
                label=item["label"],
                object_type=item["object_type"],
                object_type_id=item.get("object_type_id"),
                attributes={k: str(v) for k, v in item.get("attributes", {}).items() if v is not None},
            )
            for item in raw
        ]

    async def get_object(self, object_id: int) -> InsightObject | None:
        return next((o for o in await self.fetch_objects() if o.id == object_id), None)

    async def update_object(self, object_id: int, object_type_id: int | None, values: dict[str, str | None]) -> None:
        log.info("[mock] Insight object %s <- %s", object_id, values)

    async def close(self) -> None:
        return None
