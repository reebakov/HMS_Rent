"""Почта заказчикам по SMTP (stdlib, без новых зависимостей). Выключена, пока не заданы SMTP_HOST и SMTP_FROM."""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger(__name__)


class MailError(Exception):
    pass


def _send_sync(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    context = ssl.create_default_context()
    try:
        if settings.smtp_security == "ssl":
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout, context=context)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout)
        with client:
            if settings.smtp_security == "starttls":
                client.starttls(context=context)
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:  # пароль в тексте этих ошибок не бывает
        raise MailError(f"{type(exc).__name__}: {exc}") from exc


async def send_mail(to: str | None, subject: str, body: str) -> bool:
    """Отправляет письмо. Нет адреса, почта выключена или сервер недоступен — письма нет, операцию это не ломает."""
    if not settings.mail_enabled:
        return False
    if not to:
        log.info("Письмо «%s» не отправлено: у получателя нет почты", subject)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, body)
    except MailError as exc:
        log.warning("Письмо «%s» для %s не отправлено: %s", subject, to, exc)
        return False
    return True
