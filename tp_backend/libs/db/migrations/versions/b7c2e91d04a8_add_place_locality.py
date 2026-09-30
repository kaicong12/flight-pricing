"""add place locality

Revision ID: b7c2e91d04a8
Revises: a3f1c7e29b40
"""

import sqlalchemy as sa
from alembic import op

revision = "b7c2e91d04a8"
down_revision = "a3f1c7e29b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("places", sa.Column("locality", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("places", "locality")
