"""Письма заказчику (на почту из Bouncer): ВМ готова или не создана, срок аренды заканчивается или закончился.

Адресат — автор заказа. Тексты без технических подробностей и секретов: детали заказчик видит в «Моей аренде».
"""
from datetime import date

from app.core.config import settings
from app.integrations.mail import send_mail
from app.models import Booking, VirtualMachine


def _my_url() -> str:
    return f"{settings.public_url.rstrip('/')}/my"


def _footer() -> str:
    return f"\n\nЗаказ виден в «Моей аренде»: {_my_url()}\n\n— HMS Rent"


def _until(order: Booking | VirtualMachine) -> str:
    return f"{order.expected_return_at:%d.%m.%Y}" if order.expected_return_at else "без срока"


async def vm_ready(vm: VirtualMachine) -> None:
    ip = vm.ip_address or "появится в «Моей аренде», когда виртуалка загрузится"
    method = f" ({vm.connection_method})" if vm.connection_method else ""
    body = (
        f"Виртуальная машина {vm.name} готова (заказ №{vm.order_number}).\n\n"
        f"ОС: {vm.os_label or '—'}; {vm.cpu} ядер, {vm.ram_gb} ГБ памяти, {vm.disk_gb} ГБ диска.\n"
        f"IP: {ip}\nЛогин: {vm.connection_login}{method}\nАренда до {_until(vm)}.\n\n"
        "Пароль и порядок первого входа сообщит исполнитель. После входа смените пароль."
    )
    await send_mail(vm.user.email, f"ВМ {vm.name} готова — HMS Rent", body + _footer())


async def vm_failed(vm: VirtualMachine) -> None:
    body = (
        f"Виртуальную машину {vm.name} (заказ №{vm.order_number}) создать не удалось. Исполнители уведомлены.\n"
        "Причина видна в «Моей аренде». Заказ можно удалить и оформить заново."
    )
    await send_mail(vm.user.email, f"ВМ {vm.name} не создана — HMS Rent", body + _footer())


async def term_ending(kind: str, name: str, order: Booking | VirtualMachine, *, last_day: bool, days: int) -> None:
    when = "Сегодня последний рабочий день аренды" if last_day else f"Через {days} рабочих дней заканчивается аренда"
    body = (
        f"{when}: {kind} {name} (заказ №{order.order_number}), срок до {_until(order)}.\n\n"
        "Продлите аренду или верните ресурс в «Моей аренде». Срок без согласования — до 3 месяцев."
    )
    subject = f"{'Сегодня заканчивается' if last_day else 'Скоро заканчивается'} аренда {kind} {name} — HMS Rent"
    await send_mail(order.user.email, subject, body + _footer())


async def term_overdue(kind: str, name: str, order: Booking | VirtualMachine, today: date) -> None:
    body = (
        f"Срок аренды {kind} {name} (заказ №{order.order_number}) закончился {_until(order)}.\n\n"
        "Верните ресурс или продлите аренду в «Моей аренде»."
    )
    await send_mail(order.user.email, f"Срок аренды {kind} {name} закончился — HMS Rent", body + _footer())
