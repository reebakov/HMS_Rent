"""Нормативы исполнителей: пауза на «Заморожено» и отметки об уведомлениях в канал

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-23

Новые необязательные колонки заявок; старый код их не читает и не пишет.
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("frozen_since", sa.DateTime(timezone=True)))
    op.add_column("service_requests", sa.Column("frozen_work_seconds", sa.Integer, nullable=False, server_default="0"))
    op.add_column("service_requests", sa.Column("take_alerted_at", sa.DateTime(timezone=True)))
    op.add_column("service_requests", sa.Column("norm_alerted_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for column in ("norm_alerted_at", "take_alerted_at", "frozen_work_seconds", "frozen_since"):
        op.drop_column("service_requests", column)
