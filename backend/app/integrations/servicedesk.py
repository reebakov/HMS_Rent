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


def _client() -> httpx.AsyncClient:
    if not settings.service_desk_configured:
        raise ServiceDeskUnavailable("Service Desk не настроен: задайте SD_TOKEN (или SD_USERNAME/SD_PASSWORD) в .env")
    headers = {"Accept": "application/json", "X-ExperimentalApi": "opt-in"}
    auth = None
    if settings.sd_token:
        headers["Authorization"] = f"Bearer {settings.sd_token}"
    else:
        auth = (settings.sd_username, settings.sd_password)
    return httpx.AsyncClient(base_url=settings.sd_jira_url.rstrip("/") + "/rest/servicedeskapi",
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


async def create_request(request_type_id: int, summary: str, description: str,
                         on_behalf_of: str | None = None) -> tuple[str, SdStatus]:
    """Создаёт заявку. Если сотрудника нет в Jira, создаёт от сервисной учётки (автор — в описании)."""
    payload = {
        "serviceDeskId": str(settings.sd_service_desk_id),
        "requestTypeId": str(request_type_id),
        "requestFieldValues": {"summary": summary[:250], "description": description},
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
