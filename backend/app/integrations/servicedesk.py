"""Jira Service Desk (Server/DC): создание заявок, статус, публичные комментарии.

REST: /rest/servicedeskapi. Портал HMS Rent ходит туда от сервисной учётки-агента.
"""
import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class ServiceDeskError(Exception):
    """Ошибка Service Desk. str(exc) содержит подробности (в т.ч. начало тела ответа Jira) — только для логов и
    служебных полей; пользователю показывается user_message."""

    user_message = "Service Desk отклонил запрос, попробуйте позже"


class ServiceDeskUnavailable(ServiceDeskError):
    """Нет связи с Jira или Service Desk не настроен: запрос не дошёл до Jira."""

    user_message = "Service Desk недоступен"


@dataclass
class SdStatus:
    status: str | None
    category: str | None  # new / indeterminate / done


@dataclass
class SdComment:
    author: str
    body: str
    created: str | None  # ISO-дата
    from_portal: bool  # написано с портала (нашей сервисной учёткой от имени сотрудника)


def portal_url(issue_key: str) -> str:
    return f"{settings.sd_jira_url.rstrip('/')}/plugins/servlet/desk/portal/{settings.sd_service_desk_id}/{issue_key}"


def agent_url(issue_key: str) -> str:
    """Ссылка на заявку для сотрудника поддержки (в Jira, а не в клиентском портале)."""
    return f"{settings.sd_jira_url.rstrip('/')}/browse/{issue_key}"


def _client(api: str = "/rest/servicedeskapi") -> httpx.AsyncClient:
    if not settings.service_desk_configured:
        raise ServiceDeskUnavailable("Service Desk не настроен: задайте SD_TOKEN (или SD_USERNAME/SD_PASSWORD) в .env")
    headers = {"Accept": "application/json", "X-ExperimentalApi": "opt-in"}
    auth = None
    if settings.sd_token:
        headers["Authorization"] = f"Bearer {settings.sd_token}"
    else:
        auth = (settings.sd_username, settings.sd_password)
    return httpx.AsyncClient(base_url=settings.sd_jira_url.rstrip("/") + api,
                             headers=headers, auth=auth, verify=settings.sd_verify_ssl, timeout=20)


async def _send(http: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Запрос к Jira: недоступность и таймаут превращаются в ServiceDeskError с понятным текстом."""
    try:
        return await http.request(method, url, **kwargs)
    except httpx.HTTPError as exc:  # str(ReadTimeout()) бывает пустым — имя класса есть всегда
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise ServiceDeskUnavailable(f"Service Desk недоступен ({method} {url}): {detail}") from exc


def _json_object(resp: httpx.Response) -> dict:
    """Тело ответа как JSON-объект. HTML вместо JSON (страница логина при протухшем токене) -> ServiceDeskError."""
    try:
        data = resp.json()
    except ValueError as exc:
        raise ServiceDeskError(f"Service Desk вернул не JSON (HTTP {resp.status_code}): {resp.text[:120]!r}") from exc
    if not isinstance(data, dict):
        raise ServiceDeskError(f"Service Desk вернул неожиданный ответ (HTTP {resp.status_code}): {resp.text[:120]!r}")
    return data


def _error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):  # не JSON или JSON-массив — показываем начало тела как есть
        return f"Service Desk {resp.status_code}: {resp.text[:200]}"
    msgs = data.get("errorMessage") or "; ".join(data.get("errorMessages") or [])
    fields = "; ".join(f"{k}: {v}" for k, v in (data.get("errors") or {}).items())
    return f"Service Desk {resp.status_code}: {msgs or fields or resp.text[:200]}"


def _status(data: dict) -> SdStatus:
    cur = data.get("currentStatus")
    cur = cur if isinstance(cur, dict) else {}
    return SdStatus(status=cur.get("status"), category=(cur.get("statusCategory") or "").lower() or None)


def _created(resp: httpx.Response) -> tuple[str, SdStatus]:
    data = _json_object(resp)
    key = data.get("issueKey")
    if not key:
        raise ServiceDeskError("Service Desk не вернул ключ заявки")
    return key, _status(data)


async def create_request(request_type_id: int, description: str,
                         on_behalf_of: str | None = None) -> tuple[str, SdStatus]:
    """Создаёт заявку с одним полем — описанием. Если сотрудника нет в Jira, создаёт от сервисной учётки (автор — в описании).

    Темы в форме типа «Прочее» нет (Jira ставит название типа), поэтому тему и шапку портал меняет после создания.
    """
    payload = {
        "serviceDeskId": str(settings.sd_service_desk_id),
        "requestTypeId": str(request_type_id),
        "requestFieldValues": {"description": description},
    }
    async with _client() as http:
        if on_behalf_of and settings.sd_raise_on_behalf:
            resp = await _send(http, "POST", "/request", json={**payload, "raiseOnBehalfOf": on_behalf_of})
            if resp.status_code < 400:
                return _created(resp)
            log.info("raiseOnBehalfOf=%s не принят (%s) — создаю от сервисной учётки", on_behalf_of, resp.status_code)
        resp = await _send(http, "POST", "/request", json=payload)
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        return _created(resp)


async def get_status(issue_key: str) -> SdStatus:
    async with _client() as http:
        resp = await _send(http, "GET", f"/request/{issue_key}")
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        return _status(_json_object(resp))


async def get_comments(issue_key: str) -> list[SdComment]:
    """Только публичные комментарии — внутренние заметки агентов сотрудник не видит. Читает все страницы (до COMMENT_PAGES)."""
    comments: list[SdComment] = []
    start = 0
    async with _client() as http:
        for _ in range(COMMENT_PAGES):
            resp = await _send(http, "GET", f"/request/{issue_key}/comment",
                               params={"public": "true", "internal": "false", "start": start, "limit": COMMENT_PAGE_SIZE})
            if resp.status_code >= 400:
                raise ServiceDeskError(_error(resp))
            page = _json_object(resp)
            values = page.get("values") or []
            for c in values:
                body = c.get("body") or ""
                comments.append(SdComment(
                    author=(c.get("author") or {}).get("displayName") or "Поддержка",
                    body=body,
                    created=(c.get("created") or {}).get("iso8601"),
                    from_portal=body.startswith(PORTAL_PREFIX),
                ))
            if page.get("isLastPage", True) or not values:
                break
            start += len(values)
    return comments


# Названия статусов у Jira переведены (переход «Done» ведёт в статус «Готово»), а перевод зависит от учётки
STATUSES_IN_PROGRESS = ("In Progress", "В работе")
DONE_STATUSES = ("Done", "Готово")
PORTAL_PREFIX = "[HMS Rent] "
COMMENT_PAGE_SIZE = 100
COMMENT_PAGES = 10  # потолок: переписка длиннее 1000 комментариев не нужна, а цикл не должен быть бесконечным


async def add_comment(issue_key: str, author_name: str, text: str) -> None:
    async with _client() as http:
        resp = await _send(http, "POST", f"/request/{issue_key}/comment",
                           json={"body": f"{PORTAL_PREFIX}{author_name}: {text}", "public": True})
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))


async def request_type_fields(request_type_id: int) -> list[dict]:
    """Поля типа заявки — для CLI-проверки: какие обязательны."""
    async with _client() as http:
        resp = await _send(http, "GET", f"/servicedesk/{settings.sd_service_desk_id}/requesttype/{request_type_id}/field")
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        return _json_object(resp).get("requestTypeFields") or []


# ---------- Jira REST: история статусов и закрытие задач (DR-15072) ----------

JIRA_API = "/rest/api/2"
RESOLUTION_DONE = "Done"
RESOLUTION_REJECTED = "Rejected"


@dataclass
class SdDetails:
    taken: bool  # задача хоть раз была «В работе»: нужно, чтобы отличить «Принят» от «Снято с исполнителя»
    resolution: str | None


def _history_taken(issue: dict) -> bool:
    for entry in (issue.get("changelog") or {}).get("histories") or []:
        for item in entry.get("items") or []:
            if item.get("field") == "status" and item.get("toString") in STATUSES_IN_PROGRESS:
                return True
    return False


async def get_details(issue_key: str) -> SdDetails:
    """Резолюция и история статусов задачи (REST Jira, не Service Desk API: там истории нет)."""
    async with _client(JIRA_API) as http:
        resp = await _send(http, "GET", f"/issue/{issue_key}", params={"fields": "resolution", "expand": "changelog"})
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        issue = _json_object(resp)
    return SdDetails(taken=_history_taken(issue), resolution=((issue.get("fields") or {}).get("resolution") or {}).get("name"))


async def update_issue(issue_key: str, fields: dict) -> None:
    """Меняет шапку задачи (тему, компонент, эпик…): Service Desk при создании принимает только поля формы."""
    async with _client(JIRA_API) as http:
        resp = await _send(http, "PUT", f"/issue/{issue_key}", json={"fields": fields})
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))


async def transitions(issue_key: str) -> list[dict]:
    """Переходы, доступные сервисной учётке из текущего статуса задачи: id, имя, целевой статус."""
    async with _client(JIRA_API) as http:
        resp = await _send(http, "GET", f"/issue/{issue_key}/transitions")
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        return _json_object(resp).get("transitions") or []


def is_done_transition(transition: dict) -> bool:
    """Переход в закрытый статус: по категории целевого статуса, а не по названию (оно переведено и зависит от учётки)."""
    target = transition.get("to") or {}
    return (target.get("statusCategory") or {}).get("key") == "done" or target.get("name") in DONE_STATUSES


async def close_issue(issue_key: str, resolution: str) -> bool:
    """Закрывает задачу переходом в Done с резолюцией. False — задача уже закрыта (повтор безопасен).

    Переход ищется по целевому статусу, а не по id: id зависят от workflow проекта.
    """
    async with _client(JIRA_API) as http:
        resp = await _send(http, "GET", f"/issue/{issue_key}", params={"fields": "status"})
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        status = ((_json_object(resp).get("fields") or {}).get("status") or {})
        if (status.get("statusCategory") or {}).get("key") == "done":
            return False
    found = [t for t in await transitions(issue_key) if is_done_transition(t)]
    if not found:
        raise ServiceDeskError(f"Из статуса «{status.get('name')}» нет перехода в Done")
    async with _client(JIRA_API) as http:
        resp = await _send(http, "POST", f"/issue/{issue_key}/transitions",
                           json={"transition": {"id": found[0]["id"]}, "fields": {"resolution": {"name": resolution}}})
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
    return True
