from app.core.config import settings


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "version": "dev"}


async def test_health_reports_build_version(client, monkeypatch):
    monkeypatch.setattr(settings, "app_version", "3f9a1c2")
    assert (await client.get("/api/health")).json() == {"status": "ok", "version": "3f9a1c2"}


async def test_db_is_clean_and_migrated(session, make_department):
    dept = await make_department("QA")
    assert dept.id == 1
