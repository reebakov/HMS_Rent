"""ОС у брони ПК и заявки на сборку по запросу

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-21

`bookings.os_label` — ОС, которую заказчик выбрал для ПК из пула (её ставит исполнитель по заявке «подготовить ПК»).
`service_requests.department_id` — команда заявки без ПК и ВМ (сборка по запросу): заявку видит вся команда.
Обе колонки необязательные, старый код их не использует.
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("os_label", sa.String(64)))
    op.add_column("service_requests", sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id")))
    op.create_index("ix_service_requests_department_id", "service_requests", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_service_requests_department_id", table_name="service_requests")
    op.drop_column("service_requests", "department_id")
    op.drop_column("bookings", "os_label")
