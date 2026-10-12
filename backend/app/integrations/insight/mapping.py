"""Маппинг «атрибуты Insight -> поля портала». Настраивается в config/insight_mapping.yaml без правки кода."""
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.models.enums import ComputerStatus, Tier

FIELDS = (
    "name", "hostname", "cpu", "cpu_cores", "ram", "storage", "gpu", "os",
    "location", "serial_number", "ip_address", "status", "tier", "gateway"
)


@dataclass
class WritebackMapping:
    status_attribute: str | None = None
    status_values: dict[str, str] = field(default_factory=dict)  # наш статус -> статус Insight
    department_attribute: str | None = None
    owner_attribute: str | None = None


@dataclass
class InsightMapping:
    query: str
    schema_id: int | None = None
    attributes: dict[str, str] = field(default_factory=dict)  # наше поле -> имя атрибута Insight
    specs_attribute: str | None = None  # атрибут со строкой «CPU|RAM|GPU|Диск» (например, Comment)
    status_map: dict[str, str] = field(default_factory=dict)  # статус Insight (lower) -> ComputerStatus
    default_status: str = ComputerStatus.unknown.value
    virtual_object_types: list[str] = field(default_factory=list)
    tier_values: dict[str, str] = field(default_factory=dict)  # значение Insight (lower) -> Tier
    writeback: WritebackMapping = field(default_factory=WritebackMapping)


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


def load_mapping(path: Path) -> InsightMapping:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    wb = raw.get("writeback") or {}
    statuses = {str(k).strip().lower(): str(v) for k, v in (raw.get("status_map") or {}).items()}
    for value in statuses.values():
        ComputerStatus(value)  # упадёт с понятной ошибкой, если в YAML опечатка
    tiers = {str(k).strip().lower(): str(v) for k, v in (raw.get("tier_values") or {}).items()}
    for value in tiers.values():
        Tier(value)
    return InsightMapping(
        query=raw["query"],
        schema_id=raw.get("object_schema_id"),
        attributes={k: v for k, v in (raw.get("attributes") or {}).items() if k in FIELDS and v},
        specs_attribute=raw.get("specs_attribute") or None,
        status_map=statuses,
        default_status=raw.get("default_status", ComputerStatus.unknown.value),
        virtual_object_types=[t.lower() for t in raw.get("virtual_object_types") or []],
        tier_values=tiers,
        writeback=WritebackMapping(
            status_attribute=wb.get("status_attribute"),
            status_values={str(k): str(v) for k, v in (wb.get("status_values") or {}).items() if v},
            department_attribute=wb.get("department_attribute"),
            owner_attribute=wb.get("owner_attribute"),
        ),
    )


_NUM = re.compile(r"(\d+(?:[.,]\d+)?)")


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    m = _NUM.search(value)
    return int(float(m.group(1).replace(",", "."))) if m else None


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
    status = mapping.status_map.get((insight_status or "").lower(), mapping.default_status)
    tier_raw = get("tier")
    storage = get("storage")
    ram = get("ram")
    if storage and storage.replace(".", "").replace(",", "").isdigit():
        # «Диск: 224» — голое число. Если в Comment тот же объём с типом («SSD 224GB») — берём его, иначе «224 ГБ»
        from_specs = specs.get("storage")
        same = from_specs and parse_size_gb(from_specs) == parse_int(storage)
        storage = from_specs if same else f"{storage} ГБ"

    gateway = get("gateway")
    location = "-" # По умолчанию
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
    )
