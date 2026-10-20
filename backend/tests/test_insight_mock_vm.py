"""Mock-источник Insight: демо-номера ВМ."""
from pathlib import Path

from app.integrations.insight.mapping import InsightMapping
from app.integrations.insight.mock import MOCK_VM_ID_BASE, MockInsightSource


async def test_mock_free_vm_objects_are_demo_numbers():
    source = MockInsightSource(Path("unused.json"), InsightMapping(query="q"))
    objects = await source.fetch_free_vm_objects()
    assert [o.label for o in objects][:2] == ["A1001", "A1002"] and len(objects) == 50
    assert all(o.id >= MOCK_VM_ID_BASE and o.attributes["Status"] == "На складе" for o in objects)
    assert len({o.id for o in objects}) == 50
