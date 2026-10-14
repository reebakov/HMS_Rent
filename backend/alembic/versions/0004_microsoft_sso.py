"""Вход через Microsoft вместо Google: источник учётки у сотрудников

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # уже заведённые сотрудники (почта = логин) остаются теми же, меняется только пометка источника
    op.execute("UPDATE users SET auth_source = 'microsoft' WHERE auth_source = 'google'")
    op.alter_column("users", "auth_source", server_default="microsoft", existing_type=sa.String(16), existing_nullable=False)


def downgrade() -> None:
    op.execute("UPDATE users SET auth_source = 'google' WHERE auth_source = 'microsoft'")
    op.alter_column("users", "auth_source", server_default="google", existing_type=sa.String(16), existing_nullable=False)
