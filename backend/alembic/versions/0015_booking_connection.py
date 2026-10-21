"""Данные для подключения к ПК от исполнителя

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-22

Новые необязательные колонки брони: адрес, IP, способ подключения, кто и когда подготовил ПК. Старый код их
не читает и не пишет.
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("connection_host", sa.String(255)))
    op.add_column("bookings", sa.Column("connection_ip", sa.String(45)))
    op.add_column("bookings", sa.Column("connection_method", sa.String(8)))
    op.add_column("bookings", sa.Column("prepared_at", sa.DateTime(timezone=True)))
    op.add_column("bookings", sa.Column("prepared_by_id", sa.Integer, sa.ForeignKey("users.id")))


def downgrade() -> None:
    for column in ("prepared_by_id", "prepared_at", "connection_method", "connection_ip", "connection_host"):
        op.drop_column("bookings", column)
