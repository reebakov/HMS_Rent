"""Админка (api/routes/admin_extra.py): настройки с сайта, проверка vCenter, сотрудники.

Доступ неадминов проверяет test_api_access.py — здесь только поведение под админом.
"""
import pytest
from sqlalchemy import func, select

from app.core import admins
from app.db.session import SessionLocal
from app.integrations.vsphere import client as vsphere
from app.models import AppSetting, User, UserRole
from app.services import runtime
from app.services.runtime import RuntimeConfig

ADMIN = UserRole.admin.value
FIELDS = set(RuntimeConfig.model_fields)


@pytest.fixture
async def boss(login, make_user):
    user = await make_user("boss", role=ADMIN, display_name="Босс")
    login(user)
    return user


@pytest.fixture
def admins_file(tmp_path, monkeypatch):
    """admins_file("a@corp.io", ...) — подменяет config/admins.txt."""
    path = tmp_path / "admins.txt"
    monkeypatch.setattr(admins, "_path", lambda: path)
    monkeypatch.setattr(admins, "_cache", (-1.0, frozenset()))

    def _write(*lines: str):
        path.write_text("\n".join(lines), encoding="utf-8")
    return _write


async def fresh_user(user_id: int) -> User:
    async with SessionLocal() as s:
        return await s.get(User, user_id)


async def users_count() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(User))


async def stored_settings() -> dict:
    async with SessionLocal() as s:
        return {r.key: r.value for r in (await s.scalars(select(AppSetting))).all()}


# ---------- GET /settings ----------

async def test_get_settings_defaults_and_shape(client, boss, api):
    r = await client.get(api("/admin/settings"))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == FIELDS | {"vsphere_configured", "vcenter_host"}
    assert body["vsphere_configured"] is False and body["vcenter_host"] == ""
    assert body["vm_enabled"] is False and body["insight_writeback"] is False
    assert (body["vm_max_per_user"], body["catalog_refresh_sec"]) == (2, 15)


async def test_get_settings_reads_values_stored_in_db(client, boss, api, session):
    session.add_all([AppSetting(key="vm_max_per_user", value=7), AppSetting(key="vm_enabled", value=True),
                     AppSetting(key="мусорный_ключ", value=1)])
    await session.commit()
    body = (await client.get(api("/admin/settings"))).json()
    assert body["vm_max_per_user"] == 7 and body["vm_enabled"] is True
    assert "мусорный_ключ" not in body


async def test_get_settings_always_fresh_ignores_cache(client, boss, api, session):
    """GET грузит с max_age=0: правка в БД видна сразу, без ожидания 5 секунд кэша."""
    assert (await client.get(api("/admin/settings"))).json()["catalog_refresh_sec"] == 15
    session.add(AppSetting(key="catalog_refresh_sec", value=60))
    await session.commit()
    assert (await client.get(api("/admin/settings"))).json()["catalog_refresh_sec"] == 60


async def test_get_settings_broken_db_value_falls_back_to_defaults(client, boss, api, session):
    session.add(AppSetting(key="vm_max_per_user", value=9999))  # вне диапазона
    await session.commit()
    r = await client.get(api("/admin/settings"))
    assert r.status_code == 200 and r.json()["vm_max_per_user"] == 2


# ---------- PATCH /settings ----------

async def test_patch_settings_persists_and_updates_runtime(client, boss, api):
    r = await client.patch(api("/admin/settings"), json={"insight_sync_interval_min": 30, "vm_enabled": True,
                                                         "insight_writeback": True})
    assert r.status_code == 200
    body = r.json()
    assert (body["insight_sync_interval_min"], body["vm_enabled"], body["insight_writeback"]) == (30, True, True)
    assert await stored_settings() == {"insight_sync_interval_min": 30, "vm_enabled": True, "insight_writeback": True}
    cur = runtime.current()
    assert cur.insight_sync_interval_min == 30 and cur.insight_writeback is True  # сразу в кэше процесса
    assert (await client.get(api("/admin/settings"))).json() == body


async def test_patch_settings_updates_existing_row_not_duplicates(client, boss, api):
    await client.patch(api("/admin/settings"), json={"vm_max_per_user": 3})
    await client.patch(api("/admin/settings"), json={"vm_max_per_user": 5})
    assert await stored_settings() == {"vm_max_per_user": 5}


async def test_patch_settings_keeps_untouched_fields(client, boss, api):
    await client.patch(api("/admin/settings"), json={"vm_max_per_user": 5})
    body = (await client.patch(api("/admin/settings"), json={"catalog_refresh_sec": 30})).json()
    assert body["vm_max_per_user"] == 5 and body["catalog_refresh_sec"] == 30


@pytest.mark.parametrize("extra", [{"vsphere_configured": True}, {"vcenter_host": "evil"}, {"role": "admin"},
                                   {"vm_max_per_usr": 4}, {"что-то": 1}])
async def test_patch_settings_rejects_unknown_and_readonly_keys(client, boss, api, extra):
    """Опечатка в ключе не должна «успешно» сохраняться впустую; запрос отклоняется целиком."""
    r = await client.patch(api("/admin/settings"), json={"vm_max_per_user": 4} | extra)
    assert r.status_code == 422 and r.json()["detail"].startswith("Некорректное значение")
    assert await stored_settings() == {} and runtime.current().vm_max_per_user == 2


async def test_patch_settings_empty_body_changes_nothing(client, boss, api):
    r = await client.patch(api("/admin/settings"), json={})
    assert r.status_code == 200 and await stored_settings() == {}


@pytest.mark.parametrize("key,lo,hi", [
    ("insight_sync_interval_min", 1, 1440), ("vm_max_per_user", 0, 50), ("vm_min_cpu", 1, 64),
    ("vm_max_cpu", 1, 64), ("vm_min_ram_gb", 1, 512), ("vm_max_ram_gb", 1, 512), ("vm_min_disk_gb", 10, 4096),
    ("vm_max_disk_gb", 10, 4096), ("catalog_refresh_sec", 5, 600),
])
async def test_patch_settings_bounds(client, boss, api, key, lo, hi):
    for ok in (lo, hi):
        r = await client.patch(api("/admin/settings"), json={key: ok})
        assert r.status_code == 200 and r.json()[key] == ok
    before = await stored_settings()
    for bad in (lo - 1, hi + 1):
        r = await client.patch(api("/admin/settings"), json={key: bad})
        assert r.status_code == 422 and r.json()["detail"].startswith("Некорректное значение")
    assert await stored_settings() == before and runtime.current().model_dump()[key] == hi


@pytest.mark.parametrize("body", [{"vm_max_per_user": "много"}, {"vm_enabled": "maybe"}, {"insight_sync_interval_min": None},
                                  {"vm_max_per_user": 2.5}, {"catalog_refresh_sec": [10]}])
async def test_patch_settings_wrong_types_422(client, boss, api, body):
    assert (await client.patch(api("/admin/settings"), json=body)).status_code == 422
    assert await stored_settings() == {}


async def test_patch_settings_invalid_value_rejects_whole_request(client, boss, api):
    """Валидация до записи: валидное поле из того же запроса тоже не сохраняется."""
    r = await client.patch(api("/admin/settings"), json={"vm_max_per_user": 10, "vm_max_cpu": 1000})
    assert r.status_code == 422
    assert await stored_settings() == {} and runtime.current().vm_max_per_user == 2


async def test_patch_settings_non_object_body_422(client, boss, api):
    assert (await client.patch(api("/admin/settings"), json=[1, 2])).status_code == 422


async def test_patch_settings_accepts_bool_coercion_from_string(client, boss, api):
    r = await client.patch(api("/admin/settings"), json={"vm_enabled": "true"})
    assert r.status_code == 200 and r.json()["vm_enabled"] is True
    assert await stored_settings() == {"vm_enabled": True}  # в базе — bool, а не строка


# ---------- POST /vsphere/check ----------

async def test_vsphere_check_ok(client, boss, api, monkeypatch):
    info = {"vcenter": "vc.local", "datacenter": "DC", "template": "tpl"}
    monkeypatch.setattr(vsphere, "check", lambda names=None: info) # <-- Добавлено names=None
    r = await client.post(api("/admin/vsphere/check"))
    assert r.status_code == 200 and r.json() == {"ok": True, **info}


async def test_vsphere_check_error_is_200_with_message(client, boss, api, monkeypatch):
    def boom(names=None): # <-- Добавлено names=None
        raise vsphere.VSphereError("vCenter недоступен: timeout")
    monkeypatch.setattr(vsphere, "check", boom)
    r = await client.post(api("/admin/vsphere/check"))
    assert r.status_code == 200 and r.json() == {"ok": False, "error": "vCenter недоступен: timeout"}


async def test_vsphere_check_not_configured_reports_error(client, boss, api):
    r = await client.post(api("/admin/vsphere/check"))
    assert r.status_code == 200
    assert r.json()["ok"] is False and "VCENTER_HOST" in r.json()["error"]


# ---------- GET /users ----------

async def test_list_users_shape_and_order(client, boss, api, make_user, make_department):
    dept = await make_department("QA")
    await make_user("zed@corp.io", auth_source="microsoft", display_name="Яна", email="zed@corp.io", department=dept)
    await make_user("abe@corp.io", auth_source="microsoft", display_name="Аня", email="abe@corp.io", is_active=False)
    r = await client.get(api("/admin/users"))
    assert r.status_code == 200
    body = r.json()
    assert [u["display_name"] for u in body] == ["Аня", "Босс", "Яна"]  # по имени
    yana = body[2]
    assert set(yana) == {"id", "username", "display_name", "email", "auth_source", "role", "is_active", "department",
                         "last_login_at"}
    assert yana["department"] == {"id": dept.id, "name": "QA"} and yana["is_active"] is True
    assert body[0]["department"] is None and body[0]["is_active"] is False
    assert "password_hash" not in yana


async def test_list_users_role_for_local_admin_and_sso(client, boss, api, make_user, admins_file):
    admins_file("sso-boss@corp.io")
    await make_user("sso-boss@corp.io", auth_source="microsoft", email="sso-boss@corp.io", display_name="B1")
    await make_user("plain@corp.io", auth_source="microsoft", email="plain@corp.io", display_name="B2")
    # роль в БД admin, но почты нет в admins.txt — для SSO источник правды файл
    await make_user("stale@corp.io", auth_source="microsoft", email="stale@corp.io", role=ADMIN, display_name="B3")
    await make_user("local-user", auth_source="local", display_name="B4")
    roles = {u["display_name"]: u["role"] for u in (await client.get(api("/admin/users"))).json()}
    assert roles == {"Босс": "admin", "B1": "admin", "B2": "user", "B3": "user", "B4": "user"}


async def test_list_users_role_executor_from_file(client, boss, api, make_user, admins_file, monkeypatch, tmp_path):
    admins_file("both@corp.io")
    path = tmp_path / "executors.txt"
    path.write_text("worker@corp.io\nboth@corp.io", encoding="utf-8")
    monkeypatch.setattr(admins, "_executors_path", lambda: path)
    monkeypatch.setattr(admins, "_executors_cache", (-1.0, frozenset()))
    await make_user("worker@corp.io", auth_source="bouncer", email="worker@corp.io", display_name="W")
    await make_user("both@corp.io", auth_source="bouncer", email="both@corp.io", display_name="A")
    roles = {u["display_name"]: u["role"] for u in (await client.get(api("/admin/users"))).json()}
    assert roles == {"Босс": "admin", "W": "executor", "A": "admin"}  # администратор важнее исполнителя


async def test_list_users_empty_admins_file_missing(client, boss, api, monkeypatch, tmp_path):
    monkeypatch.setattr(admins, "_path", lambda: tmp_path / "нет-файла.txt")
    monkeypatch.setattr(admins, "_cache", (-1.0, frozenset()))
    assert (await client.get(api("/admin/users"))).status_code == 200


# ---------- POST /users ----------

async def test_add_user_defaults(client, boss, api, admins_file):
    admins_file()
    r = await client.post(api("/admin/users"), json={"email": "New.Person@Corp.IO"})
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "new.person@corp.io" and body["email"] == "new.person@corp.io"
    assert body["display_name"] == "new.person" and body["auth_source"] == "microsoft"
    assert body["role"] == "user" and body["is_active"] is True and body["department"] is None
    assert body["last_login_at"] is None
    db = await fresh_user(body["id"])
    assert db.password_hash is None and db.role == "user" and db.auth_source == "microsoft"


async def test_add_user_with_name_and_department(client, boss, api, make_department):
    dept = await make_department("QA")
    r = await client.post(api("/admin/users"), json={"email": "a@b.io", "display_name": "Анна Петрова",
                                                     "department_id": dept.id})
    assert r.status_code == 201
    assert r.json()["display_name"] == "Анна Петрова" and r.json()["department"] == {"id": dept.id, "name": "QA"}
    assert (await fresh_user(r.json()["id"])).department_id == dept.id


async def test_add_user_trims_whitespace(client, boss, api):
    r = await client.post(api("/admin/users"), json={"email": " Pad@Corp.io ", "display_name": "   "})
    assert r.status_code == 201
    assert r.json()["username"] == "pad@corp.io" and r.json()["display_name"] == "pad"  # «   » — как «не указано»


async def test_add_user_in_admins_file_shows_admin_role(client, boss, api, admins_file):
    admins_file("future-boss@corp.io")
    r = await client.post(api("/admin/users"), json={"email": "future-boss@corp.io"})
    assert r.json()["role"] == "admin"
    assert (await fresh_user(r.json()["id"])).role == "user"  # в БД роль обычная — права дают на каждом запросе по файлу


async def test_add_user_duplicate_409_case_insensitive(client, boss, api, make_user):
    await make_user("dup@corp.io", auth_source="microsoft", email="dup@corp.io")
    before = await users_count()
    r = await client.post(api("/admin/users"), json={"email": "DUP@corp.io"})
    assert r.status_code == 409 and r.json()["detail"] == "Такой сотрудник уже есть"
    assert await users_count() == before


async def test_add_user_unknown_department_404(client, boss, api):
    before = await users_count()
    r = await client.post(api("/admin/users"), json={"email": "a@b.io", "department_id": 999})
    assert r.status_code == 404 and r.json()["detail"] == "Отдел не найден"
    assert await users_count() == before


@pytest.mark.parametrize("body", [{}, {"email": None}, {"email": "no-at-sign"}, {"email": "a b@c.io"}, {"email": "   "},
                                  {"email": "a@b"}, {"email": "@b.io"}, {"email": "a@"}, {"email": "x" * 256 + "@b.io"},
                                  {"email": "a@b.io", "display_name": "n" * 256}, {"email": "a@b.io", "department_id": "x"}])
async def test_add_user_validation_422(client, boss, api, body):
    before = await users_count()
    assert (await client.post(api("/admin/users"), json=body)).status_code == 422
    assert await users_count() == before


# ---------- PATCH /users/{id} ----------

@pytest.fixture
async def emp(make_user):
    return await make_user("emp@corp.io", auth_source="microsoft", email="emp@corp.io", display_name="Сотрудник")


async def test_update_user_set_and_clear_department(client, boss, api, emp, make_department):
    dept = await make_department("QA")
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"department_id": dept.id})
    assert r.status_code == 200 and r.json()["department"] == {"id": dept.id, "name": "QA"}
    assert (await fresh_user(emp.id)).department_id == dept.id
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"department_id": None})
    assert r.json()["department"] is None and (await fresh_user(emp.id)).department_id is None


async def test_update_user_change_department_moves_user(client, boss, api, make_user, make_department):
    d1, d2 = await make_department("QA"), await make_department("Dev")
    emp = await make_user("emp@corp.io", auth_source="microsoft", email="emp@corp.io", department=d1)
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"department_id": d2.id})
    assert r.json()["department"]["name"] == "Dev" and (await fresh_user(emp.id)).department_id == d2.id


async def test_update_user_unknown_department_404_unchanged(client, boss, api, emp, make_department):
    dept = await make_department("QA")
    await client.patch(api(f"/admin/users/{emp.id}"), json={"department_id": dept.id})
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"department_id": 999, "is_active": False})
    assert r.status_code == 404 and r.json()["detail"] == "Отдел не найден"
    db = await fresh_user(emp.id)
    assert db.department_id == dept.id and db.is_active is True


async def test_update_user_deactivate_and_reactivate(client, boss, api, emp, login, make_department):
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (await fresh_user(emp.id)).is_active is False
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"is_active": True})
    assert r.json()["is_active"] is True and (await fresh_user(emp.id)).is_active is True


async def test_update_user_deactivated_user_loses_access(client, boss, api, emp, make_department):
    from app.core.config import settings
    from app.core.security import create_session_token
    await client.patch(api(f"/admin/users/{emp.id}"), json={"is_active": False})
    client.cookies.set(settings.cookie_name, create_session_token(emp.id, emp.username, emp.role))
    assert (await client.get(api("/catalog/summary"))).status_code == 401


async def test_update_user_cannot_block_self(client, boss, api):
    r = await client.patch(api(f"/admin/users/{boss.id}"), json={"is_active": False})
    assert r.status_code == 409 and r.json()["detail"] == "Нельзя заблокировать самого себя"
    assert (await fresh_user(boss.id)).is_active is True


async def test_update_self_other_fields_allowed(client, boss, api, make_department):
    dept = await make_department("QA")
    r = await client.patch(api(f"/admin/users/{boss.id}"), json={"department_id": dept.id, "is_active": True})
    assert r.status_code == 200 and r.json()["department"]["name"] == "QA" and r.json()["is_active"] is True


async def test_update_user_empty_body_is_noop(client, boss, api, emp):
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={})
    assert r.status_code == 200 and r.json()["username"] == "emp@corp.io" and r.json()["is_active"] is True


async def test_update_user_cannot_change_role_or_identity(client, boss, api, emp, admins_file):
    """Через PATCH роль, имя и почту не меняются (повышение прав — только через admins.txt)."""
    admins_file()
    r = await client.patch(api(f"/admin/users/{emp.id}"),
                           json={"role": "admin", "username": "hacked", "email": "h@x.io", "display_name": "H"})
    assert r.status_code == 200 and r.json()["role"] == "user"
    db = await fresh_user(emp.id)
    assert (db.role, db.username, db.email, db.display_name) == ("user", "emp@corp.io", "emp@corp.io", "Сотрудник")


async def test_update_user_role_follows_admins_file(client, boss, api, emp, admins_file):
    admins_file("emp@corp.io")
    assert (await client.patch(api(f"/admin/users/{emp.id}"), json={})).json()["role"] == "admin"


async def test_update_user_404(client, boss, api):
    r = await client.patch(api("/admin/users/999"), json={"is_active": False})
    assert r.status_code == 404 and r.json()["detail"] == "Сотрудник не найден"


@pytest.mark.parametrize("body", [{"is_active": "maybe"}, {"department_id": "x"}, {"department_id": []}])
async def test_update_user_validation_422(client, boss, api, emp, body):
    assert (await client.patch(api(f"/admin/users/{emp.id}"), json=body)).status_code == 422


async def test_update_user_null_is_active_does_not_block(client, boss, api, emp):
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"is_active": None})
    assert r.status_code == 422
    assert (await fresh_user(emp.id)).is_active is True


async def test_update_user_department_zero_is_client_error(client, boss, api, emp):
    r = await client.patch(api(f"/admin/users/{emp.id}"), json={"department_id": 0})
    assert r.status_code == 404
    r = await client.post(api("/admin/users"), json={"email": "new@b.io", "department_id": 0})
    assert r.status_code == 404


async def test_add_user_long_email_is_client_error(client, boss, api):
    r = await client.post(api("/admin/users"), json={"email": "x" * 150 + "@b.io"})
    assert r.status_code == 422
