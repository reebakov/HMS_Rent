"""Маппинг «атрибуты Insight -> поля портала». Настраивается в config/insight_mapping.yaml без правки кода."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from app.models.enums import ComputerStatus, Tier

FIELDS = (
    "name", "hostname", "cpu", "cpu_cores", "ram", "storage", "gpu", "os",
    "location", "serial_number", "ip_address", "status", "tier", "gateway",
    # поля аренды: читаются из Insight и пишутся обратно (см. docs/INSIGHT_SETUP.md)
    "pool", "team", "usage_period", "order_number",
)


@dataclass
class WritebackMapping:
    status_attribute: str | None = None
    status_values: dict[str, str] = field(default_factory=dict)  # наш статус -> статус Insight
    vm_status_values: dict[str, str] = field(default_factory=dict)  # taken / free -> статус объекта ВМ в Insight
    department_attribute: str | None = None  # «Команда-получатель»
    owner_attribute: str | None = None
    pool_attribute: str | None = None  # «Пул выдачи»
    period_attribute: str | None = None  # «Срок использования»
    order_attribute: str | None = None  # «Номер заказа»


@dataclass
class InsightMapping:
    query: str
    schema_id: int | None = None
    attributes: dict[str, str] = field(default_factory=dict)  # наше поле -> имя атрибута Insight
    specs_attribute: str | None = None  # атрибут со строкой «CPU|RAM|GPU|Диск» (например, Comment)
    status_map: dict[str, str] = field(default_factory=dict)  # статус Insight (lower) -> ComputerStatus
    default_status: str = ComputerStatus.unknown.value
    virtual_object_types: list[str] = field(default_factory=list)
    vm_free_query: str | None = None  # объекты ВМ «На складе»: из них берётся номер (имя ВМ) при заказе
    tier_values: dict[str, str] = field(default_factory=dict)  # значение Insight (lower) -> Tier
    writeback: WritebackMapping = field(default_factory=WritebackMapping)

    def portal_status(self, insight_status: str | None) -> str:
        """Статус Insight -> статус ПК на портале (ComputerStatus); неописанный в status_map — default_status."""
        return self.status_map.get((insight_status or "").lower(), self.default_status)


@dataclass
class ComputerData:
    """Результат маппинга одного объекта Insight."""

    name: str
    hostname: str | None
    is_virtual: bool
    cpu: str | None
    cpu_cores: int | None
    ram_gb: int | None
    storage: str | None
    storage_gb: int | None
    gpu: str | None
    os: str | None
    location: str | None
    serial_number: str | None
    ip_address: str | None
    insight_status: str | None
    status: str  # нормализованный ComputerStatus
    tier: str | None  # категория из Insight, если такое поле есть
    pool_name: str | None = None  # «Пул выдачи»
    team_name: str | None = None  # «Команда-получатель» (отдел)
    usage_until: date | None = None  # «Срок использования»
    order_number: int | None = None  # «Номер заказа»


def load_mapping(path: Path) -> InsightMapping:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    wb = raw.get("writeback") or {}
    statuses = {str(k).strip().lower(): str(v) for k, v in (raw.get("status_map") or {}).items()}
    for value in statuses.values():
        ComputerStatus(value)  # упадёт с понятной ошибкой, если в YAML опечатка
    tiers = {str(k).strip().lower(): str(v) for k, v in (raw.get("tier_values") or {}).items()}
    for value in tiers.values():
        Tier(value)
    attrs = {k: v for k, v in (raw.get("attributes") or {}).items() if k in FIELDS and v}
    return InsightMapping(
        query=raw["query"],
        schema_id=raw.get("object_schema_id"),
        attributes=attrs,
        specs_attribute=raw.get("specs_attribute") or None,
        status_map=statuses,
        default_status=raw.get("default_status", ComputerStatus.unknown.value),
        virtual_object_types=[t.lower() for t in raw.get("virtual_object_types") or []],
        vm_free_query=raw.get("vm_free_query") or None,
        tier_values=tiers,
        writeback=WritebackMapping(
            status_attribute=wb.get("status_attribute"),
            status_values={str(k): str(v) for k, v in (wb.get("status_values") or {}).items() if v},
            vm_status_values={"taken": "Используется", "free": "На складе"}
            | {str(k): str(v) for k, v in (wb.get("vm_status_values") or {}).items() if v},
            # если в блоке writeback имя атрибута не задано — пишем туда же, откуда читаем (attributes)
            department_attribute=wb.get("department_attribute") or attrs.get("team"),
            owner_attribute=wb.get("owner_attribute"),
            pool_attribute=wb.get("pool_attribute") or attrs.get("pool"),
            period_attribute=wb.get("period_attribute") or attrs.get("usage_period"),
            order_attribute=wb.get("order_attribute") or attrs.get("order_number"),
        ),
    )


_NUM = re.compile(r"(\d+(?:[.,]\d+)?)")


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    m = _NUM.search(value)
    return int(float(m.group(1).replace(",", "."))) if m else None


_RU_MONTHS = {"янв": "Jan", "фев": "Feb", "мар": "Mar", "апр": "Apr", "май": "May", "мая": "May", "июн": "Jun",
              "июл": "Jul", "авг": "Aug", "сен": "Sep", "окт": "Oct", "ноя": "Nov", "дек": "Dec"}
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y", "%d/%b/%y", "%d/%b/%Y")


def parse_date(value: str | None) -> date | None:
    """«2026-10-20», «20.10.2026», «20/Oct/26 12:00 AM», «2026-10-20T00:00:00.000Z» -> date. Непонятное -> None."""
    if not value:
        return None
    head = re.split(r"[T\s]", value.strip(), maxsplit=1)[0]
    for ru, en in _RU_MONTHS.items():  # Jira с русской локалью отдаёт «20/окт/26»
        head = re.sub(ru + r"\w*", en, head, flags=re.I)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def parse_size_gb(value: str | None) -> int | None:
    """«512 GB», «1 TB», «SSD 1ТБ + HDD 2ТБ», «16384 MB» -> гигабайты (объёмы с единицами суммируются)."""
    if not value:
        return None
    sized = re.findall(r"(\d+(?:[.,]\d+)?)\s*(tb|тб|gb|гб|mb|мб)\b", value.lower())
    if not sized:
        return parse_int(value)  # просто число — считаем, что это ГБ
    total = 0.0
    for num, unit in sized:
        size = float(num.replace(",", "."))
        total += size * 1024 if unit in ("tb", "тб") else size / 1024 if unit in ("mb", "мб") else size
    return round(total) or None


# --- Разбор строки характеристик вида «i5-7600|8GB|HD Graphics 630|SSD 112 GB» ---
_DISK = re.compile(r"\b(ssd|hdd|nvme|m\.2|emmc|sata)\b", re.I)
_CPU = re.compile(r"\b(i[3579][-\s]?\d{3,5}\w*|ryzen|xeon|pentium|celeron|athlon|core|epyc|threadripper)", re.I)
_GPU = re.compile(r"(graphics|gtx|rtx|\bgt\s?\d|radeon|\brx\s?\d|quadro|uhd|iris|geforce|\bgpu\b)", re.I)
_RAM = re.compile(r"^\d+(?:[.,]\d+)?\s*(gb|гб|g|г)?$", re.I)


def parse_specs(text: str | None) -> dict[str, str]:
    """Берёт кусок строки между «/», в котором есть хотя бы два «|», и раскладывает части по типам.

    «10.255.212.118 порт 3 / i5-7500|15GB|HD Graphics 630|SSD 224 GB /» ->
    {"cpu": "i5-7500", "ram": "15GB", "gpu": "HD Graphics 630", "storage": "SSD 224 GB"}
    """
    if not text:
        return {}
    segment = next((s.strip() for s in text.split("/") if s.count("|") >= 2), None)
    if not segment:
        return {}
    result: dict[str, str] = {}
    for part in (p.strip() for p in segment.split("|")):
        if not part:
            continue
        if _DISK.search(part):
            result.setdefault("storage", part)
        elif _CPU.search(part):
            result.setdefault("cpu", part)
        elif _GPU.search(part):
            result.setdefault("gpu", part)
        elif _RAM.match(part):
            result.setdefault("ram", part)
    return result


def map_object(obj, mapping: InsightMapping) -> ComputerData:
    """obj — InsightObject (импорт не делаем, чтобы не было циклической зависимости)."""
    specs = parse_specs(obj.attributes.get(mapping.specs_attribute)) if mapping.specs_attribute else {}

    def get(field_name: str) -> str | None:
        attr = mapping.attributes.get(field_name)
        value = obj.attributes.get(attr) if attr else None
        if isinstance(value, str) and value.strip():
            return value.strip()
        return specs.get(field_name)  # отдельный атрибут важнее строки характеристик

    insight_status = get("status")
    status = mapping.portal_status(insight_status)
    tier_raw = get("tier")
    storage = get("storage")
    ram = get("ram")
    if storage and storage.replace(".", "").replace(",", "").isdigit():
        # «Диск: 224» — голое число. Если в Comment тот же объём с типом («SSD 224GB») — берём его, иначе «224 ГБ»
        from_specs = specs.get("storage")
        same = from_specs and parse_size_gb(from_specs) == parse_int(storage)
        storage = from_specs if same else f"{storage} ГБ"

    gateway = get("gateway")
    location = "" # По умолчанию
    if gateway:
        gw_lower = gateway.lower()
        if "aut-gz" in gw_lower:
            location = "Godzen"
        elif "aut-sib" in gw_lower:
            location = "Sib"    

    return ComputerData(
        name=get("name") or obj.label,
        hostname=get("hostname"),
        is_virtual=obj.object_type.lower() in mapping.virtual_object_types,
        cpu=get("cpu"),
        cpu_cores=parse_int(get("cpu_cores")),
        ram_gb=parse_size_gb(ram) if ram else None,
        storage=storage,
        storage_gb=parse_size_gb(storage),
        gpu=get("gpu"),
        os=get("os"),
        location=get("location") or location,
        serial_number=get("serial_number"),
        ip_address=get("ip_address"),
        insight_status=insight_status,
        status=status,
        tier=mapping.tier_values.get(tier_raw.lower()) if tier_raw else None,
        pool_name=get("pool"),
        team_name=get("team"),
        usage_until=parse_date(get("usage_period")),
        order_number=parse_int(get("order_number")),
    )
