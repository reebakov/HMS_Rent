"""Клиент Insight / Assets для Jira Server / Data Center (REST /rest/insight/1.0).

Для Jira Cloud API другой (api.atlassian.com/jsm/assets/...) — достаточно написать
ещё одну реализацию InsightSource рядом и выбрать её в factory.py.
"""
import logging

import httpx

from app.core.config import Settings
from app.integrations.insight.base import InsightError, InsightObject
from app.integrations.insight.mapping import InsightMapping

log = logging.getLogger(__name__)

ATTR_TYPE_REFERENCE = 1  # ссылка на другой объект Insight
ATTR_TYPE_USER = 2
ATTR_TYPE_STATUS = 7


class InsightClient:
    mode = "live"

    def __init__(self, settings: Settings, mapping: InsightMapping):
        if not settings.jira_url:
            raise InsightError("Не задан адрес Jira: впишите JIRA_URL в .env")
        self.mapping = mapping
        self._api = settings.insight_api
        self._page_size = settings.insight_page_size
        self._jira_url = settings.jira_url.rstrip("/")
        headers = {"Accept": "application/json"}
        auth = None
        if settings.insight_token:
            headers["Authorization"] = f"Bearer {settings.insight_token}"
        elif settings.insight_username:
            auth = (settings.insight_username, settings.insight_password)
        self._http = httpx.AsyncClient(
            base_url=settings.jira_url.rstrip("/") + "/rest/insight/1.0",
            headers=headers,
            auth=auth,
            verify=settings.insight_verify_ssl,
            timeout=30,
        )
        self._type_attrs: dict[int, dict[int, dict]] = {}  # type_id -> {attr_id: описание атрибута}
        self._status_ids: dict[str, str] | None = None

    async def close(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, **params) -> dict | list:
        """Произвольный GET (для диагностики): путь относительно /rest/insight/1.0 или абсолютный URL."""
        resp = await self._http.get(path, params=params or None)
        if resp.status_code >= 400:
            raise InsightError(f"{path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()

    async def whoami(self) -> str:
        resp = await self._http.get(self._jira_url + "/rest/api/2/myself")
        if resp.status_code == 200:
            me = resp.json()
            return f"{me.get('displayName')} ({me.get('name')})"
        return f"не авторизован (HTTP {resp.status_code}) — запросы идут анонимно"

    # ---------- чтение ----------

    async def _search(self, query: str, page: int, per_page: int) -> dict:
        endpoint, param = ("/iql/objects", "iql") if self._api == "iql" else ("/aql/objects", "qlQuery")
        params = {
            param: query,
            "page": page,
            "resultPerPage": per_page,
            "includeAttributes": "true",
            "includeTypeAttributes": "true",
        }
        if self.mapping.schema_id:
            params["objectSchemaId"] = self.mapping.schema_id
        resp = await self._http.get(endpoint, params=params)
        if resp.status_code >= 400:
            raise InsightError(f"Insight {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def _type_attributes(self, type_id: int) -> dict[int, dict]:
        if type_id not in self._type_attrs:
            resp = await self._http.get(f"/objecttype/{type_id}/attributes")
            if resp.status_code >= 400:
                raise InsightError(f"Не удалось получить атрибуты типа {type_id}: {resp.status_code}")
            self._type_attrs[type_id] = {a["id"]: a for a in resp.json()}
        return self._type_attrs[type_id]

    @staticmethod
    def _value(v: dict) -> str | None:
        if v.get("status"):
            return v["status"].get("name")
        if v.get("referencedObject"):
            return v["referencedObject"].get("label")
        if v.get("user"):
            return v["user"].get("displayName") or v["user"].get("name")
        value = v.get("displayValue", v.get("value"))
        return None if value is None else str(value)

    async def to_object(self, entry: dict) -> InsightObject:
        """Объект из ответа IQL/AQL -> InsightObject с атрибутами «имя: значение»."""
        type_id = entry["objectType"]["id"]
        type_attrs = await self._type_attributes(type_id)
        attrs: dict[str, str] = {}
        for attr in entry.get("attributes") or []:
            meta = attr.get("objectTypeAttribute") or type_attrs.get(attr.get("objectTypeAttributeId"), {})
            name = meta.get("name")
            values = [x for x in (self._value(v) for v in attr.get("objectAttributeValues") or []) if x]
            if name and values:
                attrs[name] = ", ".join(values)
        return InsightObject(
            id=entry["id"],
            key=entry.get("objectKey", ""),
            label=entry.get("label", ""),
            object_type=entry["objectType"].get("name", ""),
            object_type_id=type_id,
            attributes=attrs,
        )

    async def count(self, query: str) -> int:
        data = await self._search(query, 1, 1)
        return int(data.get("totalFilterCount") or 0)

    async def fetch_objects(self, limit: int = 0, query: str | None = None) -> list[InsightObject]:
        """Все объекты по запросу из маппинга. limit > 0 — остановиться после первых N (пробный прогон)."""
        result: list[InsightObject] = []
        page = 1
        per_page = min(self._page_size, limit) if limit else self._page_size
        while True:
            data = await self._search(query or self.mapping.query, page, per_page)
            entries = data.get("objectEntries") or []
            for entry in entries:
                result.append(await self.to_object(entry))
            total = data.get("totalFilterCount")
            if limit and len(result) >= limit:
                return result[:limit]
            if len(entries) < per_page or (total is not None and len(result) >= total) or page >= 1000:
                break
            page += 1
        log.info("Insight: получено %s объектов", len(result))
        return result

    # ---------- запись ----------

    async def _status_id(self, name: str) -> str:
        if self._status_ids is None:
            params = {"objectSchemaId": self.mapping.schema_id} if self.mapping.schema_id else {}
            resp = await self._http.get("/config/statustype", params=params)
            if resp.status_code >= 400:
                raise InsightError(f"Не удалось получить статусы Insight: {resp.status_code}")
            self._status_ids = {s["name"].lower(): str(s["id"]) for s in resp.json()}
        status_id = self._status_ids.get(name.lower())
        if status_id is None:
            raise InsightError(f"В Insight нет статуса «{name}»")
        return status_id

    async def _reference_key(self, ref_type_id: int, label: str) -> str:
        data = await self._search(f'objectTypeId = {ref_type_id} AND Label = "{label}"', 1, 1)
        entries = data.get("objectEntries") or []
        if not entries:
            raise InsightError(f"В Insight не найден объект «{label}» (тип {ref_type_id})")
        return entries[0]["objectKey"]

    async def get_object(self, object_id: int) -> InsightObject | None:
        """Один объект «прямо сейчас» — для перепроверки статуса перед бронью."""
        resp = await self._http.get(f"/object/{object_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise InsightError(f"Insight {resp.status_code}: {resp.text[:200]}")
        return await self.to_object(resp.json())

    async def update_object(self, object_id: int, object_type_id: int | None, values: dict[str, str | None]) -> None:
        if object_type_id is None:
            raise InsightError("Неизвестен тип объекта — выполните синхронизацию")
        by_name = {a["name"].lower(): a for a in (await self._type_attributes(object_type_id)).values()}
        attributes = []
        for name, value in values.items():
            meta = by_name.get(name.lower())
            if meta is None:
                raise InsightError(f"У типа объекта нет атрибута «{name}»")
            if value:
                if meta.get("type") == ATTR_TYPE_STATUS:
                    value = await self._status_id(value)
                elif meta.get("type") == ATTR_TYPE_REFERENCE:
                    value = await self._reference_key(meta["referenceObjectTypeId"], value)
            attributes.append(
                {"objectTypeAttributeId": meta["id"], "objectAttributeValues": [{"value": value}] if value else []}
            )
        resp = await self._http.put(
            f"/object/{object_id}", json={"objectTypeId": object_type_id, "attributes": attributes}
        )
        if resp.status_code >= 400:
            raise InsightError(f"Insight {resp.status_code}: {resp.text[:300]}")
