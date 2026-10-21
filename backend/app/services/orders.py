"""Сквозная нумерация заказов: каждая выдача компьютера или виртуалки получает следующий номер (1, 2, 3 …).

Номер берётся из последовательности PostgreSQL rental_order_seq, поэтому два одновременных заказа
никогда не получат один номер. Пропуски возможны (например, если заказ не создался из-за ошибки) — это нормально.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def next_order_number(session: AsyncSession) -> int:
    return int(await session.scalar(text("SELECT nextval('rental_order_seq')")))


def requester_name(user: User) -> str:
    """Имя заказчика для журналов и заявок: из профиля, форма заказа спрашивает только ник."""
    return user.display_name or user.username
