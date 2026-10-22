"""Заявки Service Desk: отметка о том, что портал отреагировал на закрытие задачи в Jira

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-22

Новая необязательная колонка; старый код её не читает и не пишет. Уже закрытые заявки помечаются обработанными, чтобы
портал не пересматривал их задним числом.
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("handled_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE service_requests SET handled_at = now() WHERE status_category = 'done'")


def downgrade() -> None:
    op.drop_column("service_requests", "handled_at")
