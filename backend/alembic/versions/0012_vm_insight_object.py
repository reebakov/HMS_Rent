"""Объект ВМ в Insight: номер и имя ВМ берутся у объекта «На складе»

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-21

`insight_object_id` и `insight_object_type_id` — объект типа Virtual, чей номер стал именем ВМ; `insight_pending` —
в Insight нужно записать текущее состояние ВМ (занята или освобождена). Один объект не может принадлежать двум живым
ВМ (частичный уникальный индекс). У прежних ВМ (rent-…) объекта нет, и в Insight они не пишутся. Старый код новые
колонки не использует.
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("virtual_machines", sa.Column("insight_object_id", sa.Integer))
    op.add_column("virtual_machines", sa.Column("insight_object_type_id", sa.Integer))
    op.add_column("virtual_machines", sa.Column("insight_pending", sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_index(
        "uq_virtual_machines_alive_insight_object", "virtual_machines", ["insight_object_id"], unique=True,
        postgresql_where=sa.text("insight_object_id IS NOT NULL AND status NOT IN ('deleted', 'failed')"),
    )


def downgrade() -> None:
    op.drop_index("uq_virtual_machines_alive_insight_object", table_name="virtual_machines")
    op.drop_column("virtual_machines", "insight_pending")
    op.drop_column("virtual_machines", "insight_object_type_id")
    op.drop_column("virtual_machines", "insight_object_id")
