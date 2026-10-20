"""ОС виртуалки и срок, записанный в аннотацию vCenter

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-20

`virtual_machines.os` (windows / linux) определяет способ подключения: RDP или VNC. У старых ВМ он выводится из названия
ОС. `notes_return_at` — срок, который сейчас записан в Notes ВМ в vCenter: worker обновляет аннотацию, когда срок
заказа (`expected_return_at`) изменился после продления. Старый код оба поля не использует.
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("virtual_machines", sa.Column("os", sa.String(16)))
    op.add_column("virtual_machines", sa.Column("notes_return_at", sa.Date))
    op.execute("""
        UPDATE virtual_machines SET os = CASE
            WHEN os_label IS NULL OR os_label ILIKE '%windows%' THEN 'windows'
            WHEN os_label ~* '(ubuntu|debian|centos|linux)' THEN 'linux'
        END
    """)


def downgrade() -> None:
    op.drop_column("virtual_machines", "notes_return_at")
    op.drop_column("virtual_machines", "os")
