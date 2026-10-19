"""Поиск по подстроке (db/search.py): «%», «_» и «\\» ищутся буквально во всех поисковых полях."""
import pytest

from app.models import AssetEvent, EventType
from app.services import inventory
from tests.sync_fakes import add_booking

NAMES = ["100%", "100x", "a_b", "axb", "back\\slash", "backXslash", "Plain"]


@pytest.fixture
async def fleet(make_computer, make_pool):
    pool = await make_pool("Main")
    return {name: await make_computer(name, pool=pool) for name in NAMES}


async def inventory_names(session, q):
    rows, _ = await inventory.list_inventory(session, q=q)
    return [r.name for r in rows]


@pytest.mark.parametrize("q, expected", [
    ("%", ["100%"]),
    ("0%", ["100%"]),
    ("_", ["a_b"]),
    ("a_b", ["a_b"]),
    ("\\", ["back\\slash"]),
    ("k\\s", ["back\\slash"]),
    ("  PLAIN ", ["Plain"]),   # регистр и пробелы по краям по-прежнему не важны
    ("100", ["100%", "100x"]),
])
async def test_inventory_search_treats_wildcards_literally(session, fleet, q, expected):
    assert sorted(await inventory_names(session, q)) == sorted(expected)


@pytest.mark.parametrize("q, expected", [("%", ["100%"]), ("_", ["a_b"]), ("\\", ["back\\slash"])])
async def test_catalog_search_treats_wildcards_literally(client, login, make_user, api, fleet, q, expected):
    login(await make_user("emp"))
    r = await client.get(api("/computers"), params={"q": q})
    assert r.status_code == 200
    assert sorted(c["name"] for c in r.json()) == expected


@pytest.mark.parametrize("q, expected", [("%", {"Анна", "Борис"}), ("_", {"Глеб", "Дина"})])
async def test_journal_search_treats_wildcards_literally(session, fleet, make_user, make_department, q, expected):
    user, dept = await make_user("emp"), await make_department("QA")
    # «%» — в имени ПК и в имени заявителя, «_» — в имени ПК и в нике
    for comp, name, nick in (("100%", "Анна", "anna"), ("100x", "Борис 5%", "boris"), ("axb", "Вера", "vera"),
                             ("a_b", "Глеб", "gleb"), ("Plain", "Дина", "d_ina")):
        await add_booking(session, fleet[comp], user, dept, requester_name=name, requester_nick=nick)
    journal = await inventory.list_journal(session, q=q)
    assert {b.requester_name.split()[0] for b in journal} == expected


@pytest.mark.parametrize("q, expected", [("%", ["50% готово"]), ("_", ["a_b сбой"])])
async def test_events_search_treats_wildcards_literally(session, fleet, q, expected):
    for text in ("50% готово", "50 готово", "a_b сбой", "axb сбой"):
        session.add(AssetEvent(computer_id=fleet["Plain"].id, event_type=EventType.admin_update, message=text))
    await session.commit()
    items, total = await inventory.list_events(session, q=q)
    assert [e.message for e in items] == expected and total == 1
