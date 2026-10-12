from functools import lru_cache

from app.core.config import settings
from app.integrations.insight.base import InsightSource
from app.integrations.insight.client import InsightClient
from app.integrations.insight.mapping import InsightMapping, load_mapping
from app.integrations.insight.mock import MockInsightSource


@lru_cache
def get_mapping() -> InsightMapping:
    return load_mapping(settings.mapping_path)


def create_insight_source() -> InsightSource:
    mapping = get_mapping()
    if settings.insight_mode == "mock":
        return MockInsightSource(settings.path(settings.mock_data_file), mapping)
    return InsightClient(settings, mapping)
