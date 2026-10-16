"""Образцы ответов Jira Insight (Server/DC, /rest/insight/1.0) для тестов клиента."""

TYPE_ID = 21
REF_TYPE_ID = 55

# атрибуты типа «Компьютер»: type 0 — текст, 1 — ссылка на объект, 7 — статус
TYPE_ATTRS = [
    {"id": 100, "name": "Name", "type": 0},
    {"id": 101, "name": "Статус", "type": 7},
    {"id": 102, "name": "Команда-получатель", "type": 1, "referenceObjectTypeId": REF_TYPE_ID},
    {"id": 103, "name": "Срок использования", "type": 0},
    {"id": 104, "name": "Номер заказа", "type": 0},
    {"id": 105, "name": "Владелец", "type": 2},
]


def val(value=None, display=None, **extra) -> dict:
    """Одно значение атрибута (objectAttributeValues[i])."""
    v = {"value": value} if display is None else {"value": value, "displayValue": display}
    v.update(extra)
    return v


def attr(attr_id: int, *values: dict, inline_meta: dict | None = None) -> dict:
    a = {"objectTypeAttributeId": attr_id, "objectAttributeValues": list(values)}
    if inline_meta is not None:
        a["objectTypeAttribute"] = inline_meta
    return a


def entry(oid: int = 1, name: str = "A001", attributes: list[dict] | None = None, *, type_id: int = TYPE_ID) -> dict:
    """Объект в ответе /iql/objects, /aql/objects и /object/{id}."""
    return {
        "id": oid,
        "objectKey": f"ITAM-{oid}",
        "label": name,
        "objectType": {"id": type_id, "name": "Компьютер"},
        "attributes": attributes if attributes is not None else [attr(100, val(name))],
    }


def page(entries: list[dict], total: int | None = None) -> dict:
    """Страница выдачи IQL/AQL."""
    data = {"objectEntries": entries, "pageSize": len(entries)}
    if total is not None:
        data["totalFilterCount"] = total
    return data
