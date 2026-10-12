"""Пулы выдачи, локальные учётки администраторов, вход через Google

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "pools",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
    )
    op.add_column("computers", sa.Column("pool_id", sa.Integer, sa.ForeignKey("pools.id")))
    op.create_index("ix_computers_pool_id", "computers", ["pool_id"])

    op.add_column("users", sa.Column("avatar_url", sa.String(500)))
    op.add_column("users", sa.Column("auth_source", sa.String(16), nullable=False, server_default="google"))
    op.add_column("users", sa.Column("password_hash", sa.String(255)))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
    op.drop_column("users", "auth_source")
    op.drop_column("users", "avatar_url")
    op.drop_index("ix_computers_pool_id", table_name="computers")
    op.drop_column("computers", "pool_id")
    op.drop_table("pools")
