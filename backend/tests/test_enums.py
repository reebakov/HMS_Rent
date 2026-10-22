"""Перечисления лежат в БД обычными строками (без миграций): значения менять нельзя."""
import json

import pytest

from app.models import ServiceRequestKind, SyncRunStatus, VmStatus
from app.models.vm import VirtualMachine


@pytest.mark.parametrize("enum, values", [
    (VmStatus, ["queued", "creating", "ready", "deleting", "deleted", "failed"]),
    (SyncRunStatus, ["running", "success", "failed"]),
    (ServiceRequestKind, ["problem", "return", "prepare", "build", "diagnose"]),
])
def test_values_are_the_strings_stored_in_db(enum, values):
    assert [m.value for m in enum] == values


@pytest.mark.parametrize("member", [VmStatus.ready, SyncRunStatus.success, ServiceRequestKind.return_])
def test_member_serializes_and_compares_as_plain_string(member):
    assert member == member.value
    assert json.dumps({"v": member}) == json.dumps({"v": member.value})


def test_alive_vm_index_predicate_matches_vm_statuses():
    """Частичный индекс уникальных имён исключает ровно «мёртвые» статусы."""
    (index,) = [i for i in VirtualMachine.__table__.indexes if i.name == "uq_virtual_machines_alive_name"]
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert predicate == f"status NOT IN ('{VmStatus.deleted}', '{VmStatus.failed}')"
