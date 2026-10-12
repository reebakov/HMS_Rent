"""Список администраторов из файла config/admins.txt (путь — ADMINS_FILE).

Файл читается заново, только если изменился (по mtime), поэтому проверка дешёвая и правки
применяются без перезапуска.
"""
from pathlib import Path

from app.core.config import settings

_cache: tuple[float, frozenset[str]] = (-1.0, frozenset())


def _path() -> Path:
    return settings.path(settings.admins_file)


def admin_emails() -> frozenset[str]:
    global _cache
    path = _path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return frozenset()
    if mtime != _cache[0]:
        lines = path.read_text(encoding="utf-8").splitlines()
        emails = frozenset(
            line.split("#", 1)[0].strip().lower() for line in lines if line.split("#", 1)[0].strip()
        )
        _cache = (mtime, emails)
    return _cache[1]


def is_admin_email(email: str | None) -> bool:
    return bool(email) and email.lower() in admin_emails()
