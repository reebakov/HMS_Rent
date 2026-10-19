"""create_insight_source / get_mapping и MockInsightSource (источник без доступа к Jira)."""
import json

import pytest

from app.core.config import Settings
from app.integrations.insight import factory
from app.integrations.insight.base import InsightError, InsightObject
from app.integrations.insight.client import InsightClient
from app.integrations.insight.mock import MockInsightSource

MAPPING_YAML = """
object_schema_id: 7
query: 'objectType = "Custom"'
attributes:
  name: "Name"
  status: "Status"
status_map:
  "ожидает": available
"""


@pytest.fixture(autouse=True)
def _fresh_mapping_cache():
    """get_mapping кэшируется (lru_cache): не даём тестам влиять друг на друга и на остальные файлы."""
    factory.get_mapping.cache_clear()
    yield
    factory.get_mapping.cache_clear()


@pytest.fixture
def use_settings(monkeypatch):
    def _use(**kw) -> Settings:
        s = Settings(_env_file=None, **kw)
        monkeypatch.setattr(factory, "settings", s)
        return s
    return _use


@pytest.fixture
def custom_mapping(tmp_path):
    p = tmp_path / "custom.yaml"
    p.write_text(MAPPING_YAML, encoding="utf-8")
    return p


# ---------- get_mapping ----------

def test_get_mapping_mock_default_file(use_settings):
    use_settings(insight_mode="mock")
    m = factory.get_mapping()
    assert m.query and "Name" in m.attributes.values()


def test_get_mapping_live_default_is_boevoy_yaml(use_settings):
    use_settings(insight_mode="live")
    m = factory.get_mapping()
    assert m.schema_id == 1 and "Automat" in m.query


def test_get_mapping_respects_insight_mapping_file(use_settings, custom_mapping):
    use_settings(insight_mode="live", insight_mapping_file=str(custom_mapping))
    m = factory.get_mapping()
    assert (m.schema_id, m.query) == (7, 'objectType = "Custom"')
    assert m.status_map == {"ожидает": "available"}


def test_get_mapping_file_wins_in_mock_mode_too(use_settings, custom_mapping):
    use_settings(insight_mode="mock", insight_mapping_file=str(custom_mapping))
    assert factory.get_mapping().schema_id == 7


def test_get_mapping_relative_path_resolved_from_backend_dir(use_settings):
    use_settings(insight_mode="live", insight_mapping_file="config/insight_mapping.mock.yaml")
    assert factory.get_mapping().query


def test_get_mapping_is_cached(use_settings):
    use_settings(insight_mode="mock")
    assert factory.get_mapping() is factory.get_mapping()


def test_get_mapping_missing_file(use_settings, tmp_path):
    use_settings(insight_mapping_file=str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        factory.get_mapping()


# ---------- create_insight_source ----------

def test_create_source_mock_mode(use_settings):
    s = use_settings(insight_mode="mock")
    src = factory.create_insight_source()
    assert isinstance(src, MockInsightSource) and src.mode == "mock"
    assert src.path == s.path("seed/mock_computers.json")
    assert src.mapping is factory.get_mapping()


def test_create_source_mock_custom_data_file(use_settings, tmp_path):
    use_settings(insight_mode="mock", mock_data_file=str(tmp_path / "x.json"))
    assert factory.create_insight_source().path == tmp_path / "x.json"


async def test_create_source_live_mode(use_settings, custom_mapping):
    use_settings(insight_mode="live", jira_url="https://jira.test", insight_token="t",
                 insight_mapping_file=str(custom_mapping))
    src = factory.create_insight_source()
    try:
        assert isinstance(src, InsightClient) and src.mode == "live"
        assert src.mapping.schema_id == 7
    finally:
        await src.close()


def test_create_source_live_without_jira_url(use_settings, custom_mapping):
    use_settings(insight_mode="live", jira_url="", insight_mapping_file=str(custom_mapping))
    with pytest.raises(InsightError, match="JIRA_URL"):
        factory.create_insight_source()


def test_create_source_new_instance_each_call(use_settings):
    use_settings(insight_mode="mock")
    assert factory.create_insight_source() is not factory.create_insight_source()


# ---------- MockInsightSource ----------

@pytest.fixture
def seed(tmp_path):
    items = [
        {"id": 1, "key": "ITAM-1", "label": "A001", "object_type": "Компьютер", "object_type_id": 21,
         "attributes": {"Name": "A001", "ОЗУ": 16, "Пусто": None, "Флаг": True}},
        {"id": 2, "key": "ITAM-2", "label": "A002", "object_type": "Виртуалка"},  # без attributes и object_type_id
        {"id": 3, "key": "ITAM-3", "label": "A003", "object_type": "Компьютер", "attributes": {}},
    ]
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def mock_src(seed):
    from app.integrations.insight.mapping import InsightMapping
    return MockInsightSource(seed, InsightMapping(query="q"))


async def test_mock_fetch_objects(mock_src):
    objs = await mock_src.fetch_objects()
    assert [o.id for o in objs] == [1, 2, 3]
    assert all(isinstance(o, InsightObject) for o in objs)
    first = objs[0]
    assert (first.key, first.label, first.object_type, first.object_type_id) == ("ITAM-1", "A001", "Компьютер", 21)
    # значения приводятся к строкам, None отбрасывается
    assert first.attributes == {"Name": "A001", "ОЗУ": "16", "Флаг": "True"}
    assert objs[1].object_type_id is None and objs[1].attributes == {}


async def test_mock_fetch_limit(mock_src):
    assert [o.id for o in await mock_src.fetch_objects(limit=2)] == [1, 2]
    assert len(await mock_src.fetch_objects(limit=0)) == 3
    assert len(await mock_src.fetch_objects(limit=100)) == 3


async def test_mock_get_object(mock_src):
    assert (await mock_src.get_object(3)).label == "A003"
    assert await mock_src.get_object(999) is None


async def test_mock_rereads_file_on_each_call(seed, mock_src):
    assert len(await mock_src.fetch_objects()) == 3
    seed.write_text("[]", encoding="utf-8")
    assert await mock_src.fetch_objects() == []


async def test_mock_empty_file_list(tmp_path, mock_src):
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    assert await MockInsightSource(p, mock_src.mapping).fetch_objects() == []


async def test_mock_missing_file(tmp_path, mock_src):
    src = MockInsightSource(tmp_path / "nope.json", mock_src.mapping)
    with pytest.raises(FileNotFoundError):
        await src.fetch_objects()
    with pytest.raises(FileNotFoundError):
        await src.get_object(1)


async def test_mock_invalid_json(tmp_path, mock_src):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        await MockInsightSource(p, mock_src.mapping).fetch_objects()


async def test_mock_item_without_required_field(tmp_path, mock_src):
    p = tmp_path / "bad.json"
    p.write_text('[{"id": 1, "key": "K", "label": "L"}]', encoding="utf-8")  # нет object_type
    with pytest.raises(KeyError):
        await MockInsightSource(p, mock_src.mapping).fetch_objects()


async def test_mock_update_object_is_noop_and_logs(mock_src, seed, caplog):
    import logging
    caplog.set_level(logging.INFO)
    before = seed.read_text(encoding="utf-8")
    assert await mock_src.update_object(1, 21, {"Статус": "Занят"}) is None
    assert "[mock]" in caplog.text and "Занят" in caplog.text
    assert seed.read_text(encoding="utf-8") == before  # файл не меняется


async def test_mock_close(mock_src):
    assert await mock_src.close() is None


async def test_bundled_seed_file_loads(use_settings):
    """Штатный seed/mock_computers.json читается и согласован с mock-маппингом."""
    use_settings(insight_mode="mock")
    src = factory.create_insight_source()
    objs = await src.fetch_objects()
    assert objs
    name_attr = src.mapping.attributes["name"]
    assert all(o.attributes.get(name_attr) for o in objs)
    assert len({o.id for o in objs}) == len(objs)
