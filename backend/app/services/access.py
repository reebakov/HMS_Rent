"""Доступ к заказам: автор, участник той же команды (отдела) или администратор.

Команда заказа — отдел брони или ВМ (`department_id`), команда пользователя — `users.department_id`.
"""
from sqlalchemy import ColumnElement, or_

from app.core.errors import Forbidden
from app.models import User


def is_team_member(user: User, department_id: int) -> bool:
    return user.department_id is not None and user.department_id == department_id


def can_access(user: User, owner_id: int, department_id: int) -> bool:
    return user.is_admin or owner_id == user.id or is_team_member(user, department_id)


def ensure_access(user: User, owner_id: int, department_id: int, message: str) -> None:
    if not can_access(user, owner_id, department_id):
        raise Forbidden(message)


def mine_or_team(user: User, owner_col: ColumnElement, department_col: ColumnElement) -> ColumnElement[bool]:
    """SQL-условие «заказ пользователя или его команды»."""
    if user.department_id is None:
        return owner_col == user.id
    return or_(owner_col == user.id, department_col == user.department_id)
