"""Троттлинг неудачных входов.

Неудачные попытки живут в памяти процесса (backend запускается одним процессом).
Основной счётчик — по паре (логин, адрес): чужой перебор не блокирует настоящему админу вход с его адреса.
Запасной — по одному логину со всех адресов, с потолком в LOGIN_USER_LIMIT_FACTOR раз выше: если адрес
подделан (X-Forwarded-For), перебор всё равно упирается в этот потолок.
"""
import time
from collections import defaultdict

from app.core.config import settings
from app.core.errors import TooManyRequests

_failed: dict[tuple[str, str], list[float]] = defaultdict(list)
_failed_by_user: dict[str, list[float]] = defaultdict(list)
LOGIN_USER_LIMIT_FACTOR = 10
_PRUNE_ABOVE = 10_000  # ключей в словаре, после которых вычищаем устаревшие (чтобы память не росла от случайных логинов)


def _recent(store: dict, key, window: float) -> list[float]:
    """Свежие попытки по ключу; устаревшие выбрасываются, пустой ключ удаляется."""
    attempts = [t for t in store.get(key, ()) if time.time() - t < window]
    if attempts:
        store[key] = attempts
    else:
        store.pop(key, None)
    return attempts


def check(username: str, ip: str) -> None:
    window = settings.login_lock_minutes * 60
    by_pair = len(_recent(_failed, (username, ip), window))
    by_user = len(_recent(_failed_by_user, username, window))
    if by_pair >= settings.login_max_attempts or by_user >= settings.login_max_attempts * LOGIN_USER_LIMIT_FACTOR:
        raise TooManyRequests(f"Слишком много попыток. Повторите через {settings.login_lock_minutes} мин.")


def register_failure(username: str, ip: str) -> None:
    now = time.time()
    _failed[(username, ip)].append(now)
    _failed_by_user[username].append(now)
    if len(_failed) > _PRUNE_ABOVE or len(_failed_by_user) > _PRUNE_ABOVE:
        window = settings.login_lock_minutes * 60
        for key in list(_failed):
            _recent(_failed, key, window)
        for key in list(_failed_by_user):
            _recent(_failed_by_user, key, window)


def reset(username: str, ip: str) -> None:
    """Успешный вход сбрасывает счётчик пары; общий счётчик по логину сам устаревает."""
    _failed.pop((username, ip), None)
