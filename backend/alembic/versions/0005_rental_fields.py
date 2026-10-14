"""Номер заказа (сквозной, с 1), срок и номер заказа у ПК — под новые поля Insight

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_NUMBERED = """
WITH numbered AS (
    SELECT src, id, row_number() OVER (ORDER BY ts, src, id) AS n FROM (
        SELECT 'b' AS src, id, booked_at AS ts FROM bookings
        UNION ALL
        SELECT 'v' AS src, id, created_at AS ts FROM virtual_machines
    ) t
)
"""


def upgrade() -> None:
    op.execute("CREATE SEQUENCE rental_order_seq START 1")
    op.add_column("bookings", sa.Column("order_number", sa.Integer, nullable=True))
    op.add_column("virtual_machines", sa.Column("order_number", sa.Integer, nullable=True))
    op.add_column("computers", sa.Column("usage_until", sa.Date, nullable=True))
    op.add_column("computers", sa.Column("order_number", sa.Integer, nullable=True))

    # уже существующим броням и виртуалкам присваиваем номера по порядку создания (общая нумерация на обе таблицы)
    op.execute(_NUMBERED + "UPDATE bookings SET order_number = numbered.n FROM numbered "
               "WHERE numbered.src = 'b' AND numbered.id = bookings.id")
    op.execute(_NUMBERED + "UPDATE virtual_machines SET order_number = numbered.n FROM numbered "
               "WHERE numbered.src = 'v' AND numbered.id = virtual_machines.id")
    op.execute(
        "SELECT setval('rental_order_seq', "
        "(SELECT COALESCE(MAX(n), 0) + 1 FROM (SELECT order_number AS n FROM bookings "
        "UNION ALL SELECT order_number FROM virtual_machines) m), false)"
    )
    # активные брони -> зеркало на самом ПК
    op.execute(
        "UPDATE computers c SET order_number = b.order_number, usage_until = b.expected_return_at "
        "FROM bookings b WHERE b.computer_id = c.id AND b.status = 'active'"
    )

    for table in ("bookings", "virtual_machines"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN order_number SET DEFAULT nextval('rental_order_seq')")
        op.alter_column(table, "order_number", nullable=False, existing_type=sa.Integer)
        op.create_unique_constraint(f"uq_{table}_order_number", table, ["order_number"])


def downgrade() -> None:
    for table in ("bookings", "virtual_machines"):
        op.drop_constraint(f"uq_{table}_order_number", table, type_="unique")
        op.drop_column(table, "order_number")
    op.drop_column("computers", "order_number")
    op.drop_column("computers", "usage_until")
    op.execute("DROP SEQUENCE rental_order_seq")
