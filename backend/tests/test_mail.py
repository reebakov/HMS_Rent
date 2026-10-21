"""Почта заказчикам по SMTP: режимы соединения, авторизация, письмо, ошибки. Сервер подменён, сети нет."""
import email
import smtplib

import pytest

from app.core.config import settings
from app.integrations import mail


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_on: str | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.args = (host, port, timeout)
        self.ssl = context is not None
        self.calls: list[str] = []
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _maybe_fail(self, step: str):
        if FakeSMTP.fail_on == step:
            raise smtplib.SMTPException("сервер отказал")

    def starttls(self, context=None):
        self.calls.append("starttls")
        self._maybe_fail("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")
        self._maybe_fail("login")

    def send_message(self, msg):
        self.calls.append("send")
        self._maybe_fail("send")
        self.sent = msg


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_on = [], None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda host, port, timeout=None, context=None: FakeSMTP(host, port, timeout, context))
    for key, value in (("smtp_host", "smtp.test"), ("smtp_port", 587), ("smtp_from", "hms-rent@corp.test"),
                       ("smtp_user", ""), ("smtp_password", ""), ("smtp_security", "starttls"), ("smtp_timeout", 9)):
        monkeypatch.setattr(settings, key, value)
    return FakeSMTP


async def test_disabled_without_host_or_sender(smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    assert await mail.send_mail("a@corp.test", "Тема", "Текст") is False
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "")
    assert await mail.send_mail("a@corp.test", "Тема", "Текст") is False
    assert smtp.instances == []


async def test_no_recipient_sends_nothing(smtp):
    assert await mail.send_mail(None, "Тема", "Текст") is False
    assert await mail.send_mail("", "Тема", "Текст") is False
    assert smtp.instances == []


async def test_starttls_message_is_sent_with_utf8_headers_and_timeout(smtp):
    assert await mail.send_mail("ivan@corp.test", "ВМ A1001 готова — HMS Rent", "Здравствуйте!\nВМ готова.") is True
    (conn,) = smtp.instances
    assert conn.args == ("smtp.test", 587, 9) and conn.calls == ["starttls", "send"]  # без логина — без login
    parsed = email.message_from_bytes(conn.sent.as_bytes())
    assert (parsed["From"], parsed["To"]) == ("hms-rent@corp.test", "ivan@corp.test")
    assert str(email.header.make_header(email.header.decode_header(parsed["Subject"]))) == "ВМ A1001 готова — HMS Rent"
    assert "ВМ готова." in conn.sent.get_content()


async def test_login_when_user_given(smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "svc-hmsrent")
    monkeypatch.setattr(settings, "smtp_password", "s3cret")
    await mail.send_mail("a@corp.test", "Тема", "Текст")
    assert smtp.instances[0].calls == ["starttls", "login:svc-hmsrent", "send"]


@pytest.mark.parametrize("security, port, calls", [
    ("ssl", 465, ["send"]),     # соединение сразу по TLS, STARTTLS не нужен
    ("none", 25, ["send"]),     # внутренний relay без шифрования
])
async def test_security_modes(smtp, monkeypatch, security, port, calls):
    monkeypatch.setattr(settings, "smtp_security", security)
    monkeypatch.setattr(settings, "smtp_port", port)
    await mail.send_mail("a@corp.test", "Тема", "Текст")
    conn = smtp.instances[0]
    assert (conn.calls, conn.args[1], conn.ssl) == (calls, port, security == "ssl")


@pytest.mark.parametrize("step", ["starttls", "login", "send"])
async def test_server_error_is_swallowed_and_logged_without_password(smtp, monkeypatch, caplog, step):
    monkeypatch.setattr(settings, "smtp_user", "svc")
    monkeypatch.setattr(settings, "smtp_password", "TOP-SECRET-PASSWORD")
    smtp.fail_on = step
    with caplog.at_level("WARNING", logger="app.integrations.mail"):
        assert await mail.send_mail("a@corp.test", "Тема", "Текст") is False
    assert "не отправлено" in caplog.text and "TOP-SECRET-PASSWORD" not in caplog.text


async def test_connection_error_is_swallowed(monkeypatch, smtp):
    def boom(*args, **kwargs):
        raise ConnectionRefusedError("нет соединения")
    monkeypatch.setattr(smtplib, "SMTP", boom)
    assert await mail.send_mail("a@corp.test", "Тема", "Текст") is False
