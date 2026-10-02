"""name the city each trip day is in

Revision ID: a9d4c6e1f3b2
Revises: c3d8e2a6f1b4
"""

import sqlalchemy as sa
from alembic import op

revision = "a9d4c6e1f3b2"
down_revision = "c3d8e2a6f1b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trip_days",
        sa.Column("trip_id", sa.String(36), sa.ForeignKey("trips.trip_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("day_index", sa.Integer, primary_key=True),
        sa.Column("city_id", sa.String(255), sa.ForeignKey("cities.city_id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("trip_days")
