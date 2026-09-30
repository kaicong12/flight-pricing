"""add expenses, shares and settlements

Revision ID: a3f1c7e29b40
Revises: f0c93a1d5b62
"""

import sqlalchemy as sa
from alembic import op

revision = "a3f1c7e29b40"
down_revision = "f0c93a1d5b62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("expense_id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), sa.ForeignKey("trips.trip_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("payer_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("spent_on", sa.Date(), nullable=False),
        sa.Column("place_id", sa.String(255), sa.ForeignKey("places.place_id")),
        sa.Column("block_id", sa.String(36)),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("amount_cents > 0", name="ck_expense_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_expense_currency"),
        sa.CheckConstraint("place_id IS NULL OR block_id IS NULL", name="ck_expense_block"),
    )
    op.create_index("ix_expenses_trip", "expenses", ["trip_id", "spent_on"])

    op.create_table(
        "expense_shares",
        sa.Column("expense_id", sa.String(36),
                  sa.ForeignKey("expenses.expense_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("amount_cents >= 0", name="ck_share_amount"),
    )

    op.create_table(
        "settlements",
        sa.Column("settlement_id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), sa.ForeignKey("trips.trip_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("from_user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("to_user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("amount_cents > 0", name="ck_settlement_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_settlement_currency"),
        sa.CheckConstraint("from_user_id <> to_user_id", name="ck_settlement_parties"),
    )
    op.create_index("ix_settlements_trip", "settlements", ["trip_id"])


def downgrade() -> None:
    op.drop_table("settlements")
    op.drop_table("expense_shares")
    op.drop_index("ix_expenses_trip", table_name="expenses")
    op.drop_table("expenses")
