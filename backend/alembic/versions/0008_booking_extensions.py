"""Продления брони

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "booking_extensions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("old_return_at", sa.Date),
        sa.Column("new_return_at", sa.Date, nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", TZ),
        sa.Column("acknowledged_by_id", sa.Integer, sa.ForeignKey("users.id")),
    )
    op.create_index("ix_booking_extensions_booking_id", "booking_extensions", ["booking_id"])


def downgrade() -> None:
    op.drop_table("booking_extensions")
