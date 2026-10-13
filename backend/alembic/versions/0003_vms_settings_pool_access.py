"""Пулы по отделам, отдел у сотрудника, настройки на сайте, виртуалки из конструктора

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "pool_departments",
        sa.Column("pool_id", sa.Integer, sa.ForeignKey("pools.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
    )
    op.add_column("users", sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id")))

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", postgresql.JSONB),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "virtual_machines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("cpu", sa.Integer, nullable=False),
        sa.Column("ram_gb", sa.Integer, nullable=False),
        sa.Column("disk_gb", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("requester_name", sa.String(255), nullable=False),
        sa.Column("requester_nick", sa.String(128), nullable=False),
        sa.Column("purpose", sa.Text),
        sa.Column("expected_return_at", sa.Date),
        sa.Column("vsphere_moid", sa.String(64)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("power_state", sa.String(32)),
        sa.Column("ready_at", TZ),
        sa.Column("released_at", TZ),
        sa.Column("deleted_at", TZ),
        sa.Column("released_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("attrs", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_virtual_machines_name", "virtual_machines", ["name"])
    op.create_index("ix_virtual_machines_status", "virtual_machines", ["status"])
    op.create_index("ix_virtual_machines_user_id", "virtual_machines", ["user_id"])
    # одно и то же имя не может быть у двух «живых» виртуалок
    op.create_index(
        "uq_virtual_machines_alive_name", "virtual_machines", ["name"],
        unique=True, postgresql_where=sa.text("status NOT IN ('deleted', 'failed')"),
    )


def downgrade() -> None:
    op.drop_table("virtual_machines")
    op.drop_table("app_settings")
    op.drop_column("users", "department_id")
    op.drop_table("pool_departments")
