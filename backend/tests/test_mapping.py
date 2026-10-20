"""Маппинг Insight -> поля портала: чистые функции, без БД."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.insight.mapping import (
    InsightMapping,
    load_mapping,
    map_object,
    parse_date,
    parse_int,
    parse_size_gb,
    parse_specs,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


# ---------- parse_int ----------

@pytest.mark.parametrize("raw, expected", [
    ("8", 8), ("8 ядер", 8), ("v2", 2), ("1,5", 1), ("16.9 GB", 16),
    (None, None), ("", None), ("нет", None),
])
def test_parse_int(raw, expected):
    assert parse_int(raw) == expected


# ---------- parse_date ----------

@pytest.mark.parametrize("raw", [
    "2026-10-20", "20.10.2026", "20.10.26", "20/10/2026", "20-10-2026",
    "20/Oct/26 12:00 AM", "20/окт/26 12:00 AM", "20/Окт/2026",
    "2026-10-20T00:00:00.000Z", "2026-10-20 14:30:00", "  2026-10-20  ",
])
def test_parse_date_ok(raw):
    assert parse_date(raw) == date(2026, 10, 20)


@pytest.mark.parametrize("raw, expected", [("05/мая/26", date(2026, 5, 5)), ("01/янв/27", date(2027, 1, 1))])
def test_parse_date_ru_months(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "мусор", "2026-13-45", "31.02.2026", "бессрочно"])
def test_parse_date_garbage(raw):
    assert parse_date(raw) is None


# ---------- parse_size_gb ----------

@pytest.mark.parametrize("raw, expected", [
    ("512 GB", 512), ("512GB", 512), ("1 TB", 1024), ("1,5 TB", 1536),
    ("SSD 1ТБ + HDD 2ТБ", 3072),          # объёмы суммируются
    ("SSD 512 GB + HDD 1 TB", 1536),
    ("16384 MB", 16), ("224", 224), ("16", 16),
    (None, None), ("", None), ("нет данных", None), ("0 GB", None),
])
def test_parse_size_gb(raw, expected):
    assert parse_size_gb(raw) == expected


# ---------- parse_specs ----------

def test_parse_specs_docstring_example():
    text = "10.255.212.118 порт 3 / i5-7500|15GB|HD Graphics 630|SSD 224 GB /"
    assert parse_specs(text) == {"cpu": "i5-7500", "ram": "15GB", "gpu": "HD Graphics 630", "storage": "SSD 224 GB"}


@pytest.mark.parametrize("text, expected", [
    ("i5-7600|8GB|HD Graphics 630|SSD 112 GB", {"cpu": "i5-7600", "ram": "8GB", "gpu": "HD Graphics 630",
                                                "storage": "SSD 112 GB"}),   # без «/»
    ("Ryzen 5 3600|16|RTX 3060|NVMe 1 TB", {"cpu": "Ryzen 5 3600", "ram": "16", "gpu": "RTX 3060",
                                            "storage": "NVMe 1 TB"}),       # ОЗУ голым числом
    ("a||i7-9700|32 GB", {"cpu": "i7-9700", "ram": "32 GB"}),               # пустая часть и неопознанная «a»
    (" i5-7500 | 8GB | SSD 1 ТБ ", {"cpu": "i5-7500", "ram": "8GB", "storage": "SSD 1 ТБ"}),  # пробелы обрезаются
    ("i5-7500|i7-9700|8GB", {"cpu": "i5-7500", "ram": "8GB"}),              # дубль типа: первый побеждает
])
def test_parse_specs_parts(text, expected):
    assert parse_specs(text) == expected


@pytest.mark.parametrize("text", [
    None, "", "просто комментарий", "10.0.0.1 / порт 3 /", "i5-7500|8GB", "a / b|c / d",  # < 2 разделителей «|»
])
def test_parse_specs_garbage(text):
    assert parse_specs(text) == {}


def test_parse_specs_takes_first_segment_with_pipes():
    assert parse_specs("x|y / i5-7500|8GB|SSD 1 TB / i3-1000|4GB|HDD 1 TB")["cpu"] == "i5-7500"


# ---------- map_object ----------

def obj(attributes=None, label="PC-label", object_type="Компьютер"):
    return SimpleNamespace(attributes=attributes or {}, label=label, object_type=object_type)


def mp(**kw) -> InsightMapping:
    kw.setdefault("query", "q")
    return InsightMapping(**kw)


def test_map_object_basic_fields():
    m = mp(attributes={"name": "Name", "cpu": "CPU", "cpu_cores": "Cores", "ram": "RAM", "os": "OS",
                       "usage_period": "Until", "order_number": "Order", "pool": "Pool", "team": "Team"})
    d = map_object(obj({"Name": " A001 ", "CPU": "i7", "Cores": "8 ядер", "RAM": "16384 MB", "OS": "Win",
                        "Until": "20.10.2026", "Order": "42", "Pool": "QA", "Team": "Тесты"}), m)
    assert (d.name, d.cpu, d.cpu_cores, d.ram_gb, d.os) == ("A001", "i7", 8, 16, "Win")
    assert (d.usage_until, d.order_number, d.pool_name, d.team_name) == (date(2026, 10, 20), 42, "QA", "Тесты")


def test_map_object_name_falls_back_to_label():
    assert map_object(obj({"Name": "  "}, label="AUT-1"), mp(attributes={"name": "Name"})).name == "AUT-1"


def test_map_object_empty_values_are_none():
    d = map_object(obj({}), mp(attributes={"cpu": "CPU", "ram": "RAM"}))
    assert (d.cpu, d.ram_gb, d.storage, d.storage_gb, d.usage_until, d.order_number) == (None,) * 6


SPECS = "10.0.0.1 / i5-7500|8GB|HD Graphics 630|SSD 224GB /"


@pytest.mark.parametrize("disk, comment, storage, gb", [
    ("224", SPECS, "SSD 224GB", 224),                       # тот же объём в Comment — берём с типом диска
    ("224", SPECS.replace("224GB", "112GB"), "224 ГБ", 224),  # объём другой — остаётся голое число с «ГБ»
    ("224", None, "224 ГБ", 224),                           # Comment нет
    ("SSD 512 GB", SPECS, "SSD 512 GB", 512),               # не голое число — не трогаем
    (None, SPECS, "SSD 224GB", 224),                        # атрибута нет — из specs
])
def test_map_object_storage(disk, comment, storage, gb):
    attrs = {k: v for k, v in {"Диск": disk, "Comment": comment}.items() if v}
    d = map_object(obj(attrs), mp(attributes={"storage": "Диск"}, specs_attribute="Comment"))
    assert (d.storage, d.storage_gb) == (storage, gb)


def test_map_object_specs_fill_gaps_but_attribute_wins():
    m = mp(attributes={"cpu": "CPU"}, specs_attribute="Comment")
    d = map_object(obj({"CPU": "Xeon E5", "Comment": SPECS}), m)
    assert (d.cpu, d.ram_gb, d.gpu) == ("Xeon E5", 8, "HD Graphics 630")


@pytest.mark.parametrize("gateway, expected", [
    ("aut-gz-gw01", "Godzen"), ("AUT-GZ-GW01", "Godzen"), ("aut-sib-gw02", "Sib"),
    ("other-gw", ""), (None, ""),
])
def test_map_object_location_from_gateway(gateway, expected):
    attrs = {"GW": gateway} if gateway else {}
    assert map_object(obj(attrs), mp(attributes={"gateway": "GW"})).location == expected


def test_map_object_explicit_location_beats_gateway():
    m = mp(attributes={"gateway": "GW", "location": "Loc"})
    assert map_object(obj({"GW": "aut-gz-1", "Loc": "Москва"}), m).location == "Москва"


@pytest.mark.parametrize("raw, expected", [
    ("Свободен", "available"), ("свободен", "available"), ("  СВОБОДЕН ", "available"),  # регистр и пробелы
    ("что-то новое", "unknown"), (None, "unknown"),
])
def test_map_object_status(raw, expected):
    m = mp(attributes={"status": "Статус"}, status_map={"свободен": "available"})
    d = map_object(obj({"Статус": raw} if raw else {}), m)
    assert d.status == expected
    assert d.insight_status == (raw.strip() if raw else None)


def test_map_object_custom_default_status():
    m = mp(attributes={"status": "S"}, status_map={}, default_status="maintenance")
    assert map_object(obj({"S": "x"}), m).status == "maintenance"


@pytest.mark.parametrize("raw, expected", [
    ("Свободен", "available"), ("свободен", "available"), ("что-то новое", "unknown"), (None, "unknown"), ("", "unknown"),
])
def test_portal_status(raw, expected):
    assert mp(status_map={"свободен": "available"}).portal_status(raw) == expected


def test_portal_status_custom_default():
    assert mp(status_map={}, default_status="maintenance").portal_status("x") == "maintenance"


@pytest.mark.parametrize("raw, expected", [("Мощный", "powerful"), ("слабый", "weak"), ("???", None), (None, None)])
def test_map_object_tier(raw, expected):
    m = mp(attributes={"tier": "Класс"}, tier_values={"мощный": "powerful", "слабый": "weak"})
    assert map_object(obj({"Класс": raw} if raw else {}), m).tier == expected


@pytest.mark.parametrize("object_type, expected", [("Виртуальная машина", True), ("ВИРТУАЛЬНАЯ МАШИНА", True),
                                                   ("Компьютер", False)])
def test_map_object_is_virtual(object_type, expected):
    m = mp(virtual_object_types=["виртуальная машина"])
    assert map_object(obj(object_type=object_type), m).is_virtual is expected


# ---------- load_mapping ----------

def _yaml(tmp_path, body: str) -> Path:
    p = tmp_path / "m.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_mapping_ok(tmp_path):
    m = load_mapping(_yaml(tmp_path, """
query: 'objectType = "PC"'
virtual_object_types: ["VM"]
attributes: {name: Name, unknown_field: X, cpu: ""}
status_map: {" Свободен ": available}
tier_values: {Мощный: powerful}
writeback: {status_attribute: S}
"""))
    assert m.attributes == {"name": "Name"}            # лишние поля и пустые значения отброшены
    assert m.status_map == {"свободен": "available"}   # ключи нормализованы
    assert m.virtual_object_types == ["vm"] and m.tier_values == {"мощный": "powerful"}
    assert m.default_status == "unknown" and m.writeback.status_attribute == "S"


def test_load_mapping_writeback_falls_back_to_attributes(tmp_path):
    m = load_mapping(_yaml(tmp_path, "query: q\nattributes: {pool: Пул, team: Команда}\n"))
    assert (m.writeback.pool_attribute, m.writeback.department_attribute) == ("Пул", "Команда")


@pytest.mark.parametrize("body", [
    "query: q\nstatus_map: {x: availabel}\n",
    "query: q\ntier_values: {x: superpowerful}\n",
])
def test_load_mapping_typo_raises(tmp_path, body):
    with pytest.raises(ValueError):
        load_mapping(_yaml(tmp_path, body))


def test_load_mapping_requires_query(tmp_path):
    with pytest.raises(KeyError):
        load_mapping(_yaml(tmp_path, "attributes: {name: Name}\n"))


@pytest.mark.parametrize("name", ["insight_mapping.mock.yaml", "insight_mapping.yaml"])
def test_real_mapping_files_load(name):
    m = load_mapping(CONFIG_DIR / name)
    assert m.query and m.attributes and m.status_map


def test_load_mapping_vm_settings(tmp_path):
    m = load_mapping(_yaml(tmp_path, """
query: q
vm_free_query: 'objectType = "Automat" AND Type IN ("Virtual")'
writeback: {vm_status_values: {free: "Склад"}}
"""))
    assert m.vm_free_query == 'objectType = "Automat" AND Type IN ("Virtual")'
    assert m.writeback.vm_status_values == {"taken": "Используется", "free": "Склад"}  # не заданное — по умолчанию


def test_load_mapping_vm_defaults(tmp_path):
    m = load_mapping(_yaml(tmp_path, "query: q\n"))
    assert m.vm_free_query is None
    assert m.writeback.vm_status_values == {"taken": "Используется", "free": "На складе"}


def test_prod_mapping_has_free_vm_query():
    m = load_mapping(CONFIG_DIR / "insight_mapping.yaml")
    assert m.vm_free_query == 'objectType = "Automat" AND "Status" IN ("На складе") AND "Type" IN ("Virtual")'
