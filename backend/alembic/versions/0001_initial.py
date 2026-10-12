"""Начальная схема: пользователи, отделы, компьютеры, бронирования, журнал, синхронизации

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)
JSONB_EMPTY = sa.text("'{}'::jsonb")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("ad_department", sa.String(255)),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("last_login_at", TZ),
        *timestamps(),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "departments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("code", sa.String(64)),
        sa.Column("head_name", sa.String(255)),
        sa.Column("is_active", sa.Boolean, nullable=False),
        *timestamps(),
    )

    op.create_table(
        "computers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("insight_object_id", sa.Integer, unique=True),
        sa.Column("insight_object_type_id", sa.Integer),
        sa.Column("insight_key", sa.String(64)),
        sa.Column("insight_object_type", sa.String(128)),
        sa.Column("insight_status", sa.String(128)),
        sa.Column("attributes", postgresql.JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("synced_at", TZ),
        sa.Column("is_archived", sa.Boolean, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("hostname", sa.String(128)),
        sa.Column("is_virtual", sa.Boolean, nullable=False),
        sa.Column("cpu", sa.String(255)),
        sa.Column("cpu_cores", sa.Integer),
        sa.Column("ram_gb", sa.Integer),
        sa.Column("storage", sa.String(255)),
        sa.Column("storage_gb", sa.Integer),
        sa.Column("gpu", sa.String(255)),
        sa.Column("os", sa.String(128)),
        sa.Column("location", sa.String(255)),
        sa.Column("serial_number", sa.String(128)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("tier_override", sa.String(16)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id")),
        sa.Column("note", sa.Text),
        sa.Column("writeback_pending", sa.Boolean, nullable=False),
        sa.Column("writeback_error", sa.Text),
        *timestamps(),
    )
    op.create_index("ix_computers_name", "computers", ["name"])
    op.create_index("ix_computers_tier", "computers", ["tier"])
    op.create_index("ix_computers_status", "computers", ["status"])

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("computer_id", sa.Integer, sa.ForeignKey("computers.id"), nullable=False),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requester_name", sa.String(255), nullable=False),
        sa.Column("requester_nick", sa.String(128), nullable=False),
        sa.Column("purpose", sa.Text),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("booked_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("expected_return_at", sa.Date),
        sa.Column("returned_at", TZ),
        sa.Column("returned_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("return_comment", sa.Text),
        *timestamps(),
    )
    op.create_index("ix_bookings_computer_id", "bookings", ["computer_id"])
    op.create_index("ix_bookings_department_id", "bookings", ["department_id"])
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])
    op.create_index(
        "uq_bookings_active_computer", "bookings", ["computer_id"],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "asset_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("computer_id", sa.Integer, sa.ForeignKey("computers.id"), nullable=False),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("bookings.id")),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(128)),
        sa.Column("to_status", sa.String(128)),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, server_default=JSONB_EMPTY, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_asset_events_computer_id", "asset_events", ["computer_id"])
    op.create_index("ix_asset_events_event_type", "asset_events", ["event_type"])
    op.create_index("ix_asset_events_created_at", "asset_events", ["created_at"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", TZ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("total", sa.Integer, nullable=False),
        sa.Column("created", sa.Integer, nullable=False),
        sa.Column("updated", sa.Integer, nullable=False),
        sa.Column("archived", sa.Integer, nullable=False),
        sa.Column("error", sa.Text),
    )


def downgrade() -> None:
    for table in ("sync_runs", "asset_events", "bookings", "computers", "departments", "users"):
        op.drop_table(table)
