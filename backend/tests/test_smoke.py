async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_db_is_clean_and_migrated(session, make_department):
    dept = await make_department("QA")
    assert dept.id == 1
