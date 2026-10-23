"""Заявка на сборку хранит данные заказа

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-23

Новая необязательная колонка заявок (JSONB): из неё исполнитель выдаёт собранный ПК заказчику (номер заказа, срок, ОС,
ник, цель). Старый код её не читает и не пишет; заявки на сборку, созданные до миграции, без неё выдаются вне портала.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("payload", JSONB))


def downgrade() -> None:
    op.drop_column("service_requests", "payload")
