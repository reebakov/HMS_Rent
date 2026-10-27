"""Метка неисправности ПК

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-27

Новая колонка computers.faulty: ПК выведен исполнителем как неисправный. Только такой ПК портал пишет в Insight
статусом «ТО»; обслуживание, пришедшее из Insight, не переписывается. Старый код колонку не читает и не пишет
(server_default). Уже выведенные из пула ПК с открытой диагностикой помечаются неисправными.
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("computers", sa.Column("faulty", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""
        UPDATE computers SET faulty = true
        WHERE status = 'maintenance' AND EXISTS (
            SELECT 1 FROM service_requests r
            WHERE r.computer_id = computers.id AND r.kind = 'diagnose' AND r.portal_done_at IS NULL)
    """)


def downgrade() -> None:
    op.drop_column("computers", "faulty")
