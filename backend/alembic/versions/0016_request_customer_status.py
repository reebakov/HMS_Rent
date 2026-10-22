"""Статус заявки для заказчика: история взятия в работу, резолюция, комментарий к «Заморожено»

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-22

Новые необязательные колонки заявок Service Desk; старый код их не читает и не пишет.
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("was_taken", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("service_requests", sa.Column("resolution", sa.String(64)))
    op.add_column("service_requests", sa.Column("status_note", sa.Text))


def downgrade() -> None:
    for column in ("status_note", "resolution", "was_taken"):
        op.drop_column("service_requests", column)
