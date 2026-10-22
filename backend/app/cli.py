"""Служебные команды. Запуск:  docker compose exec backend python -m app.cli <команда>

  create-admin <логин> [--name "Имя Фамилия"]   — создать локального администратора (пароль спросит)
  set-password <логин>                           — сменить пароль локальной учётке
  users                                          — список пользователей портала
  disable <логин> / enable <логин>               — заблокировать / разблокировать
  insight-check [--sample 5] [--query IQL]       — проверить подключение к Insight и маппинг
  insight-check --breakdown Type                 — сколько объектов с каждым значением атрибута
  sd-transitions <ключ>                          — какие переходы Jira доступны сервисной учётке на задаче и видна ли история
  push-pools                                     — записать в Insight («Пул выдачи») пулы всех ПК, что сейчас на портале
"""
import argparse
import asyncio
import getpass
import json
import sys

from sqlalchemy import select, update

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Computer, User, UserRole


def ask_password() -> str:
    while True:
        first = getpass.getpass("Пароль (мин. 10 символов): ")
        if len(first) < 10:
            print("Слишком короткий пароль")
            continue
        if first != getpass.getpass("Повторите пароль: "):
            print("Пароли не совпали")
            continue
        return first


async def create_admin(username: str, name: str | None) -> None:
    username = username.strip().lower()
    async with SessionLocal() as session:
        if await session.scalar(select(User).where(User.username == username)):
            sys.exit(f"Пользователь «{username}» уже есть. Сменить пароль: set-password {username}")
        session.add(User(
            username=username, display_name=name or username, auth_source="local",
            password_hash=hash_password(ask_password()), role=UserRole.admin.value,
        ))
        await session.commit()
    print(f"✓ Администратор «{username}» создан. Вход: форма «Вход для администраторов».")


async def set_password(username: str) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == username.lower()))
        if user is None or user.auth_source != "local":
            sys.exit("Локальная учётка не найдена (пароли есть только у локальных администраторов)")
        user.password_hash = hash_password(ask_password())
        await session.commit()
    print("✓ Пароль обновлён")


async def set_active(username: str, active: bool) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == username.lower()))
        if user is None:
            sys.exit("Пользователь не найден")
        user.is_active = active
        await session.commit()
    print(f"✓ {username}: {'активен' if active else 'заблокирован'}")


async def list_users() -> None:
    async with SessionLocal() as session:
        users = (await session.scalars(select(User).order_by(User.role, User.username))).all()
    for u in users:
        last = f"{u.last_login_at:%d.%m.%Y %H:%M}" if u.last_login_at else "—"
        print(f"{u.username:40} {u.auth_source:7} {u.role:6} {'on ' if u.is_active else 'OFF'}  вход: {last}")


async def push_pools() -> None:
    """Одноразово после включения «Пул выдачи»: отправить в Insight пулы, которые уже назначены на портале."""
    async with SessionLocal() as session:
        result = await session.execute(
            update(Computer).where(Computer.pool_id.is_not(None), Computer.is_archived.is_(False))
            .values(writeback_pending=True)
        )
        await session.commit()
    print(f"✓ В очередь на запись в Insight поставлено ПК: {result.rowcount}. Воркер отправит их за несколько минут "
          f"(нужен INSIGHT_WRITEBACK=true или включатель на странице «Настройки»).")


async def insight_check(sample: int, query: str | None, breakdown: str | None) -> None:
    from collections import Counter

    from app.integrations.insight.client import InsightClient
    from app.integrations.insight.mapping import load_mapping, map_object
    from app.services.tiering import classify

    path = settings.path(settings.insight_mapping_file or "config/insight_mapping.yaml")
    mapping = load_mapping(path)
    query = query or mapping.query
    client = InsightClient(settings, mapping)
    print(f"Jira: {settings.jira_url}   маппинг: {path.name}")
    try:
        print("Учётка:", await client.whoami())
        if not breakdown:
            schemas = (await client.get("/objectschema/list")).get("objectschemas", [])
            print("\nСхемы объектов:")
            for s in schemas:
                print(f"  id={s['id']:<4} {s['name']}  (объектов: {s.get('objectCount', '?')})")
            if mapping.schema_id:
                types = await client.get(f"/objectschema/{mapping.schema_id}/objecttypes/flat", includeObjectCounts="true")
                print(f"\nТипы объектов схемы {mapping.schema_id}:")
                for t in sorted(types, key=lambda t: -(t.get("objectCount") or 0)):
                    print(f"  id={t['id']:<5} {t['name']}  (объектов: {t.get('objectCount', '?')})")
                statuses = await client.get("/config/statustype", objectSchemaId=mapping.schema_id)
                print("\nСтатусы:", ", ".join(sorted({s["name"] for s in statuses})))

        print(f"\nЗапрос: {query}")
        print(f"Найдено объектов: {await client.count(query):,}".replace(",", " "))

        if breakdown:
            # точные количества по значениям атрибута (значения берутся из первых 1000 объектов)
            objects = await client.fetch_objects(limit=1000, query=query)
            values = Counter(o.attributes.get(breakdown, "") for o in objects)
            print(f"\nРазбивка по «{breakdown}»:")
            for value, _ in values.most_common():
                if not value:
                    print(f"  (пусто)  — встречается в выборке: {values[value]}")
                    continue
                n = await client.count(f'({query}) AND "{breakdown}" = "{value}"')
                print(f"  {value}: {n:,}".replace(",", " "))
            return

        objects = await client.fetch_objects(limit=sample, query=query)
        if objects:
            attrs = await client._type_attributes(objects[0].object_type_id)
            print(f"Атрибуты типа «{objects[0].object_type}»: " + ", ".join(a["name"] for a in attrs.values()))
            known = {a["name"].lower() for a in attrs.values()}
            missing = [f"{field} → «{name}»" for field, name in mapping.attributes.items() if name.lower() not in known]
            if missing:
                print("⚠ В Insight нет атрибутов из маппинга (проверьте написание): " + "; ".join(missing))
        for obj in objects:
            data = map_object(obj, mapping)
            tier = data.tier or classify(is_virtual=data.is_virtual, ram_gb=data.ram_gb, gpu=data.gpu)
            print(f"\n— {obj.key} {obj.label} [{obj.object_type}]")
            print("  в Insight:", json.dumps(obj.attributes, ensure_ascii=False))
            print(f"  на портале: CPU={data.cpu} | ОЗУ={data.ram_gb} ГБ | GPU={data.gpu} | диск={data.storage} | "
                  f"статус «{data.insight_status}» → {data.status} | категория {tier}")
            print(f"  аренда: пул={data.pool_name} | команда={data.team_name} | срок={data.usage_until} | "
                  f"заказ №={data.order_number}")
        if not objects:
            print("Запрос ничего не вернул — проверьте query и права учётки на схему.")
    finally:
        await client.close()


async def sd_check() -> None:
    """Проверка Service Desk: доступ и поля типа «Прочее» (какие обязательны)."""
    from app.integrations import servicedesk as sd

    type_id = settings.sd_request_type
    print(f"Service Desk: {settings.sd_jira_url}, id={settings.sd_service_desk_id}")
    try:
        fields = await sd.request_type_fields(type_id)
    except sd.ServiceDeskError as exc:
        print(f"\nПрочее ({type_id}): ОШИБКА — {exc}")
        return
    print(f"\nПрочее ({type_id}):")
    for f in fields:
        mark = "ОБЯЗАТЕЛЬНО" if f.get("required") else ""
        print(f"  {f.get('fieldId'):24} {f.get('name')} {mark}")
    print("\nПортал заполняет summary и description; остальное в шапке задачи он ставит после создания (SD_ISSUE_FIELDS).")


async def sd_transitions(issue_key: str) -> None:
    """Проверка прав сервисной учётки на задаче: доступные переходы и чтение истории статусов."""
    from app.integrations import servicedesk as sd

    print(f"Задача {issue_key} ({settings.sd_jira_url})")
    try:
        found = await sd.transitions(issue_key)
    except sd.ServiceDeskError as exc:
        print(f"\nПереходы: ОШИБКА — {exc}")
    else:
        print("\nПереходы из текущего статуса:")
        for t in found:
            print(f"  {t.get('id'):>4}  {t.get('name')} -> {(t.get('to') or {}).get('name')}")
        if not any(sd.is_done_transition(t) for t in found):
            print("  (перехода в Done нет: портал не сможет закрыть задачу из этого статуса)")
    try:
        details = await sd.get_details(issue_key)
    except sd.ServiceDeskError as exc:
        print(f"\nИстория и резолюция: ОШИБКА — {exc}")
    else:
        print(f"\nИстория читается: брали в работу — {'да' if details.taken else 'нет'}, резолюция — {details.resolution or '—'}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Служебные команды HMS Rent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("username")
    p.add_argument("--name")
    sub.add_parser("set-password").add_argument("username")
    sub.add_parser("disable").add_argument("username")
    sub.add_parser("enable").add_argument("username")
    sub.add_parser("users")
    sub.add_parser("push-pools")
    sub.add_parser("sd-check")
    sub.add_parser("sd-transitions").add_argument("issue_key")
    p = sub.add_parser("insight-check")
    p.add_argument("--sample", type=int, default=5, help="сколько объектов показать")
    p.add_argument("--query", help="свой IQL-запрос вместо query из маппинга")
    p.add_argument("--breakdown", metavar="АТРИБУТ", help="посчитать объекты по значениям атрибута, например Type")
    args = parser.parse_args()

    commands = {
        "sd-check": sd_check,
        "sd-transitions": lambda: sd_transitions(args.issue_key),
        "create-admin": lambda: create_admin(args.username, args.name),
        "set-password": lambda: set_password(args.username),
        "disable": lambda: set_active(args.username, False),
        "enable": lambda: set_active(args.username, True),
        "users": list_users,
        "push-pools": push_pools,
        "insight-check": lambda: insight_check(args.sample, args.query, args.breakdown),
    }
    asyncio.run(commands[args.cmd]())


if __name__ == "__main__":
    main()
