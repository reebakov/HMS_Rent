"""«Диагностика комплекта» знает ПК и пул, из которого его вывели

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-23

Новые необязательные колонки заявок; старый код их не читает и не пишет. Заявки, созданные до миграции, остаются без ПК.
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("computer_id", sa.Integer, sa.ForeignKey("computers.id")))
    op.create_index("ix_service_requests_computer_id", "service_requests", ["computer_id"])
    op.add_column("service_requests", sa.Column("pool_id", sa.Integer, sa.ForeignKey("pools.id", ondelete="SET NULL")))
    op.add_column("service_requests", sa.Column("portal_done_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("service_requests", "portal_done_at")
    op.drop_column("service_requests", "pool_id")
    op.drop_index("ix_service_requests_computer_id", table_name="service_requests")
    op.drop_column("service_requests", "computer_id")
