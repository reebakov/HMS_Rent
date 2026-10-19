"""Пароли, JWT-сессии, OAuth state: без БД."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    ALGORITHM,
    create_oauth_state,
    create_session_token,
    decode_session_token,
    hash_password,
    read_oauth_state,
    verify_password,
)

# ---------- Пароли ----------

def test_password_roundtrip():
    h = hash_password("пароль-123")
    assert h.startswith("scrypt$") and "пароль" not in h
    assert verify_password("пароль-123", h)


def test_password_wrong_and_salted():
    h = hash_password("secret")
    assert not verify_password("Secret", h) and not verify_password("", h)
    assert hash_password("secret") != h  # соль разная


@pytest.mark.parametrize("stored", [
    None, "", "garbage", "scrypt$1$2", "bcrypt$16384$8$1$AAAA$AAAA",   # нет формата / чужой алгоритм
    "scrypt$x$8$1$AAAA$AAAA",                                          # параметр не число
    "scrypt$16384$8$1$!!!$!!!",                                        # битый base64
    "scrypt$16385$8$1$AAAA$AAAA",                                      # n не степень двойки
    "scrypt$16384$8$1$AAAA$",                                          # пустой дайджест
])
def test_verify_password_broken_stored(stored):
    assert verify_password("secret", stored) is False


# ---------- JWT ----------

def _claims(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def test_session_token_roundtrip():
    data = decode_session_token(create_session_token(7, "ivanov", "admin"))
    assert (data["sub"], data["usr"], data["role"]) == ("7", "ivanov", "admin")


def test_session_token_expired():
    claims = _claims(create_session_token(1, "u", "user"))
    claims["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert decode_session_token(jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)) is None


def test_session_token_other_secret():
    claims = _claims(create_session_token(1, "u", "user"))
    assert decode_session_token(jwt.encode(claims, "another-secret-key-32-bytes-long!!", algorithm=ALGORITHM)) is None


def test_session_token_tampered_payload():
    """Роль подменена в payload, подпись осталась от старого токена."""
    head, _, sig = create_session_token(1, "u", "user").split(".")
    forged = jwt.encode({**_claims(create_session_token(1, "u", "user")), "role": "admin"}, "x" * 32, algorithm=ALGORITHM)
    assert decode_session_token(f"{head}.{forged.split('.')[1]}.{sig}") is None


def test_session_token_alg_none():
    claims = {"sub": "1", "usr": "u", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    assert decode_session_token(jwt.encode(claims, None, algorithm="none")) is None


@pytest.mark.parametrize("token", ["", "abc", "a.b.c"])
def test_session_token_garbage(token):
    assert decode_session_token(token) is None


# ---------- OAuth state ----------

def test_oauth_state_roundtrip():
    state, nonce, cookie = create_oauth_state("/catalog")
    data = read_oauth_state(cookie)
    assert (data["state"], data["nonce"], data["next"]) == (state, nonce, "/catalog")
    assert state != nonce


def test_oauth_state_unique():
    assert create_oauth_state("/")[0] != create_oauth_state("/")[0]


@pytest.mark.parametrize("cookie", [None, "", "garbage"])
def test_oauth_state_invalid_cookie(cookie):
    assert read_oauth_state(cookie) is None


def test_oauth_state_expired():
    _, _, cookie = create_oauth_state("/")
    claims = _claims(cookie)
    claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert read_oauth_state(jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)) is None
