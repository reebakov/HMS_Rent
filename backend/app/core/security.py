"""Сессии (JWT в httpOnly-cookie), хэши паролей локальных учёток, state для OAuth."""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def create_session_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "usr": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.session_ttl_hours),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_view_as_token(admin_id: int, user_id: int) -> str:
    """Режим «Открыть как пользователь»: подписанная пара «кто смотрит → чьими глазами». Живёт столько же, сколько сессия."""
    now = datetime.now(timezone.utc)
    payload = {"adm": admin_id, "sub": str(user_id), "iat": now, "exp": now + timedelta(hours=settings.session_ttl_hours)}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------- Пароли (scrypt из стандартной библиотеки) ----------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# ---------- Короткоживущий state для входа через Bouncer ----------

def create_oauth_state(next_path: str) -> tuple[str, str, str]:
    """Возвращает (state, nonce, подписанная cookie с ними)."""
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    payload = {"state": state, "nonce": nonce, "next": next_path,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}
    return state, nonce, jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def read_oauth_state(cookie: str | None) -> dict | None:
    return decode_session_token(cookie) if cookie else None
