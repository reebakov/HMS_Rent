"""Проверка ВМ исполнителем: кто и когда подтвердил, пересоздание

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-23

Новые необязательные колонки виртуалок; статус checking — обычная строка (колонка status не ограничена перечислением).
Старый код их не читает и не пишет.
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("virtual_machines", sa.Column("checked_at", sa.DateTime(timezone=True)))
    op.add_column("virtual_machines", sa.Column("checked_by_id", sa.Integer, sa.ForeignKey("users.id")))
    op.add_column("virtual_machines", sa.Column("recreate", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for column in ("recreate", "checked_by_id", "checked_at"):
        op.drop_column("virtual_machines", column)
