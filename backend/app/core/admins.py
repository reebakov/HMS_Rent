"""Списки ролей из файлов: администраторы — config/admins.txt (ADMINS_FILE), исполнители — config/executors.txt
(EXECUTORS_FILE).

Файл читается заново, только если изменился (по mtime), поэтому проверка дешёвая и правки
применяются без перезапуска.
"""
from pathlib import Path

from app.core.config import settings

_Cache = tuple[float, frozenset[str]]

_cache: _Cache = (-1.0, frozenset())
_executors_cache: _Cache = (-1.0, frozenset())


def _path() -> Path:
    return settings.path(settings.admins_file)


def _executors_path() -> Path:
    return settings.path(settings.executors_file)


def _read(path: Path, cache: _Cache) -> _Cache:
    """Почты из файла (по одной в строке, «#» — комментарий); нет файла — пустой список."""
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return (-1.0, frozenset())
    if mtime == cache[0]:
        return cache
    lines = path.read_text(encoding="utf-8").splitlines()
    return (mtime, frozenset(
        line.split("#", 1)[0].strip().lower() for line in lines if line.split("#", 1)[0].strip()
    ))


def admin_emails() -> frozenset[str]:
    global _cache
    _cache = _read(_path(), _cache)
    return _cache[1]


def executor_emails() -> frozenset[str]:
    global _executors_cache
    _executors_cache = _read(_executors_path(), _executors_cache)
    return _executors_cache[1]


def is_admin_email(email: str | None) -> bool:
    return bool(email) and email.lower() in admin_emails()


def is_executor_email(email: str | None) -> bool:
    return bool(email) and email.lower() in executor_emails()
