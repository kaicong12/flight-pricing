"""let a payment name the expense it paid a share of

Revision ID: e2c7a4f9b1d3
Revises: a9d4c6e1f3b2
"""

import sqlalchemy as sa
from alembic import op

revision = "e2c7a4f9b1d3"
down_revision = "a9d4c6e1f3b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settlements", sa.Column(
        "expense_id", sa.String(36),
        sa.ForeignKey("expenses.expense_id", ondelete="CASCADE")))
    op.create_index("ix_settlements_expense", "settlements", ["expense_id"])


def downgrade() -> None:
    op.drop_index("ix_settlements_expense", table_name="settlements")
    op.drop_column("settlements", "expense_id")
