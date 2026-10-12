"""Уведомления. Сейчас — входящий вебхук Mattermost; выключено, если URL не задан."""
import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


async def notify(text: str) -> None:
    if not settings.mattermost_webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            await http.post(settings.mattermost_webhook_url, json={"text": text, "username": settings.app_name})
    except httpx.HTTPError as exc:  # уведомление не должно ломать бронирование
        log.warning("Mattermost недоступен: %s", exc)
