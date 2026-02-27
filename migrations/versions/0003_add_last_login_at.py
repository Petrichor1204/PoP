"""add last login timestamp

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("users", "last_login_at")
