"""«Сегодня» и «сейчас» портала: по DISPLAY_TIMEZONE, а не по часовому поясу сервера или контейнера.

Сроки возврата, просрочки и валидация дат должны считать день одинаково — иначе у границы суток
ПК одновременно «просрочен» в одном экране и «не просрочен» в другом.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def display_tz() -> ZoneInfo:
    return ZoneInfo(settings.display_timezone)


def now() -> datetime:
    return datetime.now(display_tz())


def today() -> date:
    return now().date()
