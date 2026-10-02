"""tag an expense with a free-text category

Revision ID: c3d8e2a6f1b4
Revises: b6e2f9a4c1d7
"""

import sqlalchemy as sa
from alembic import op

revision = "c3d8e2a6f1b4"
down_revision = "b6e2f9a4c1d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("expenses", sa.Column("category", sa.String(40)))


def downgrade() -> None:
    op.drop_column("expenses", "category")
