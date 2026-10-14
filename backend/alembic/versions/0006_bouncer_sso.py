"""Microsoft -> Bouncer SSO

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("UPDATE users SET auth_source = 'bouncer' WHERE auth_source = 'microsoft'")
    op.alter_column("users", "auth_source", server_default="bouncer", existing_type=sa.String(16), existing_nullable=False)

def downgrade() -> None:
    op.execute("UPDATE users SET auth_source = 'microsoft' WHERE auth_source = 'bouncer'")
    op.alter_column("users", "auth_source", server_default="microsoft", existing_type=sa.String(16), existing_nullable=False)