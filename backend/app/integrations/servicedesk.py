"""Jira Service Desk (Server/DC): создание заявок, статус, публичные комментарии.

REST: /rest/servicedeskapi. Портал HMS Rent ходит туда от сервисной учётки-агента.
"""
import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class ServiceDeskError(Exception):
    pass


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
        raise ServiceDeskError("Service Desk не настроен: задайте SD_TOKEN (или SD_USERNAME/SD_PASSWORD) в .env")
    headers = {"Accept": "application/json", "X-ExperimentalApi": "opt-in"}
    auth = None
    if settings.sd_token:
        headers["Authorization"] = f"Bearer {settings.sd_token}"
    else:
        auth = (settings.sd_username, settings.sd_password)
    return httpx.AsyncClient(base_url=settings.sd_jira_url.rstrip("/") + "/rest/servicedeskapi",
                             headers=headers, auth=auth, verify=settings.sd_verify_ssl, timeout=20)


def _error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        msgs = data.get("errorMessage") or "; ".join(data.get("errorMessages") or [])
        fields = "; ".join(f"{k}: {v}" for k, v in (data.get("errors") or {}).items())
        return f"Service Desk {resp.status_code}: {msgs or fields or resp.text[:200]}"
    except ValueError:
        return f"Service Desk {resp.status_code}: {resp.text[:200]}"


def _status(data: dict) -> SdStatus:
    cur = data.get("currentStatus") or {}
    return SdStatus(status=cur.get("status"), category=(cur.get("statusCategory") or "").lower() or None)


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
            resp = await http.post("/request", json={**payload, "raiseOnBehalfOf": on_behalf_of})
            if resp.status_code < 400:
                data = resp.json()
                return data["issueKey"], _status(data)
            log.info("raiseOnBehalfOf=%s не принят (%s) — создаю от сервисной учётки", on_behalf_of, resp.status_code)
        resp = await http.post("/request", json=payload)
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        data = resp.json()
        return data["issueKey"], _status(data)


async def get_status(issue_key: str) -> SdStatus:
    async with _client() as http:
        resp = await http.get(f"/request/{issue_key}")
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        return _status(resp.json())


async def get_comments(issue_key: str) -> list[SdComment]:
    """Только публичные комментарии — внутренние заметки агентов сотрудник не видит."""
    async with _client() as http:
        resp = await http.get(f"/request/{issue_key}/comment", params={"public": "true", "internal": "false",
                                                                       "limit": 100})
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        comments = []
        for c in resp.json().get("values", []):
            body = c.get("body") or ""
            comments.append(SdComment(
                author=(c.get("author") or {}).get("displayName") or "Поддержка",
                body=body,
                created=(c.get("created") or {}).get("iso8601"),
                from_portal=body.startswith(PORTAL_PREFIX),
            ))
        return comments


PORTAL_PREFIX = "[HMS Rent] "


async def add_comment(issue_key: str, author_name: str, text: str) -> None:
    async with _client() as http:
        resp = await http.post(f"/request/{issue_key}/comment",
                               json={"body": f"{PORTAL_PREFIX}{author_name}: {text}", "public": True})
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))


async def request_type_fields(request_type_id: int) -> list[dict]:
    """Поля типа заявки — для CLI-проверки: какие обязательны."""
    async with _client() as http:
        resp = await http.get(f"/servicedesk/{settings.sd_service_desk_id}/requesttype/{request_type_id}/field")
        if resp.status_code >= 400:
            raise ServiceDeskError(_error(resp))
        return resp.json().get("requestTypeFields", [])
