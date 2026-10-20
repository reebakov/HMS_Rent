"""Продления виртуалок: журнал продлений ведётся и для ВМ

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20

`booking_extensions` хранит продления и ПК, и ВМ: добавлена `vm_id`, `booking_id` стал необязательным,
CHECK требует ровно одно из двух. Миграция только добавляет колонку и ослабляет ограничение: прежняя версия
кода продолжает работать (она пишет только `booking_id`).
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

CHECK = "ck_booking_extensions_one_target"


def upgrade() -> None:
    op.add_column("booking_extensions", sa.Column("vm_id", sa.Integer, sa.ForeignKey("virtual_machines.id")))
    op.create_index("ix_booking_extensions_vm_id", "booking_extensions", ["vm_id"])
    op.alter_column("booking_extensions", "booking_id", existing_type=sa.Integer, nullable=True)
    op.create_check_constraint(op.f(CHECK), "booking_extensions", "(booking_id IS NULL) <> (vm_id IS NULL)")


def downgrade() -> None:
    op.execute("DELETE FROM booking_extensions WHERE booking_id IS NULL")  # продления ВМ в старой схеме негде хранить
    op.drop_constraint(op.f(CHECK), "booking_extensions", type_="check")
    op.alter_column("booking_extensions", "booking_id", existing_type=sa.Integer, nullable=False)
    op.drop_index("ix_booking_extensions_vm_id", table_name="booking_extensions")
    op.drop_column("booking_extensions", "vm_id")
