"""Чистая логика пулов: без БД, модели создаются в памяти."""
import pytest

from app.models import Department, Pool, User, UserRole
from app.services.pools import parse_names, pool_visible


@pytest.mark.parametrize("text, expected", [
    ("A24, A432\nA434 a442", ["a24", "a432", "a434", "a442"]),
    ("a1;a2 ,; a3", ["a1", "a2", "a3"]),
    ("A1 a1 A1, b2", ["a1", "b2"]),       # дубли убираются, порядок сохраняется
    ("  \n ,;  ", []), ("", []),
])
def test_parse_names(text, expected):
    assert parse_names(text) == expected


def make_pool(dept_ids=(), published=True) -> Pool:
    pool = Pool(name="P", is_published=published)
    pool.departments = [Department(id=i, name=f"D{i}") for i in dept_ids]
    return pool


def make_user(dept_id=None, role=UserRole.user.value) -> User:
    return User(username="u", role=role, department_id=dept_id)


def test_pool_none_invisible():
    assert pool_visible(None, make_user()) is False


@pytest.mark.parametrize("role", [UserRole.user.value, UserRole.admin.value])
def test_unpublished_invisible_even_to_admin(role):
    assert pool_visible(make_pool(published=False), make_user(role=role)) is False


@pytest.mark.parametrize("dept_id", [None, 1, 99])
def test_pool_without_departments_visible_to_all(dept_id):
    assert pool_visible(make_pool(), make_user(dept_id)) is True


@pytest.mark.parametrize("dept_id, expected", [(1, True), (2, True), (3, False), (None, False)])
def test_pool_with_departments_only_for_own(dept_id, expected):
    assert pool_visible(make_pool(dept_ids=(1, 2)), make_user(dept_id)) is expected


def test_admin_sees_restricted_pool():
    assert pool_visible(make_pool(dept_ids=(1,)), make_user(dept_id=None, role=UserRole.admin.value)) is True
