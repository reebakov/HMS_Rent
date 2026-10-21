"""Тексты писем заказчику: адресат, тема, срок, ссылка, отсутствие технических подробностей."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import customer_mail


@pytest.fixture
def sent(monkeypatch):
    out: list[tuple[str | None, str, str]] = []

    async def fake(to, subject, body):
        out.append((to, subject, body))
        return True

    monkeypatch.setattr(customer_mail, "send_mail", fake)
    monkeypatch.setattr(settings, "public_url", "https://hmsrent.example/")
    return out


def order(due: date | None = date(2026, 12, 1)):
    return SimpleNamespace(order_number=42, expected_return_at=due, user=SimpleNamespace(email="ivan@corp.test"))


async def test_term_ending_in_five_days(sent):
    await customer_mail.term_ending("ПК", "A65", order(), last_day=False, days=5)
    (to, subject, body), = sent
    assert to == "ivan@corp.test" and subject == "Скоро заканчивается аренда ПК A65 — HMS Rent"
    assert "Через 5 рабочих дней заканчивается аренда" in body and "срок до 01.12.2026" in body
    assert "https://hmsrent.example/my" in body and "//my" not in body.replace("https://", "")  # слеш не задвоен


async def test_term_ending_last_day(sent):
    await customer_mail.term_ending("ВМ", "A1001", order(), last_day=True, days=0)
    (_, subject, body), = sent
    assert subject == "Сегодня заканчивается аренда ВМ A1001 — HMS Rent"
    assert "Сегодня последний рабочий день аренды" in body


async def test_term_overdue(sent):
    await customer_mail.term_overdue("ПК", "A65", order(), date(2026, 12, 2))
    (_, subject, body), = sent
    assert subject == "Срок аренды ПК A65 закончился — HMS Rent"
    assert "закончился 01.12.2026" in body and "Верните ресурс или продлите" in body


async def test_order_without_term_says_so(sent):
    await customer_mail.term_overdue("ВМ", "A1002", order(None), date(2026, 12, 2))
    assert "без срока" in sent[0][2]
