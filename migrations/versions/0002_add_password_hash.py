"""add password hash to users

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=False, server_default=""))


def downgrade():
    op.drop_column("users", "password_hash")
