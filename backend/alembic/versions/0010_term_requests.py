"""Заявки админу на срок аренды дольше лимита

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-20

Новая таблица `term_requests`: ПК (`booking_id`) или ВМ (`vm_id`), срок, о котором просит арендатор, и решение админа.
У одного заказа ждёт решения не больше одной заявки (частичные уникальные индексы). Старый код таблицу не использует.
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "term_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("bookings.id")),
        sa.Column("vm_id", sa.Integer, sa.ForeignKey("virtual_machines.id")),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_return_at", sa.Date, nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.CheckConstraint("(booking_id IS NULL) <> (vm_id IS NULL)", name=op.f("ck_term_requests_one_target")),
    )
    op.create_index("uq_term_requests_pending_booking", "term_requests", ["booking_id"], unique=True,
                    postgresql_where=sa.text("status = 'pending' AND booking_id IS NOT NULL"))
    op.create_index("uq_term_requests_pending_vm", "term_requests", ["vm_id"], unique=True,
                    postgresql_where=sa.text("status = 'pending' AND vm_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("term_requests")
