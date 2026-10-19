"""Детали синхронизаций, заявки Service Desk, шаблоны ОС для виртуалок

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("sync_runs", sa.Column("details", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"),
                                         nullable=False))

    op.add_column("virtual_machines", sa.Column("template_key", sa.String(32)))
    op.add_column("virtual_machines", sa.Column("os_label", sa.String(64)))
    op.execute("UPDATE virtual_machines SET template_key = 'win10', os_label = 'Windows 10' WHERE template_key IS NULL")

    op.create_table(
        "service_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("bookings.id")),
        sa.Column("vm_id", sa.Integer, sa.ForeignKey("virtual_machines.id")),
        sa.Column("issue_key", sa.String(32)),
        sa.Column("summary", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(128)),
        sa.Column("status_category", sa.String(32)),
        sa.Column("error", sa.Text),
        sa.Column("last_checked_at", TZ),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
    )
    for col in ("kind", "user_id", "booking_id", "vm_id", "issue_key"):
        op.create_index(f"ix_service_requests_{col}", "service_requests", [col])


def downgrade() -> None:
    op.drop_table("service_requests")
    op.drop_column("virtual_machines", "os_label")
    op.drop_column("virtual_machines", "template_key")
    op.drop_column("sync_runs", "details")
