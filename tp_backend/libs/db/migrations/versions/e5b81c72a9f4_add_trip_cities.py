"""add trip_cities

Revision ID: e5b81c72a9f4
Revises: d4f7b2c09e81
Create Date: 2026-09-24 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e5b81c72a9f4'
down_revision: Union[str, Sequence[str], None] = 'd4f7b2c09e81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trip_cities",
        sa.Column("trip_id", sa.String(36), sa.ForeignKey("trips.trip_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("city_id", sa.String(255), sa.ForeignKey("cities.city_id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_trip_cities_city", "trip_cities", ["city_id"])
    op.execute("""
        INSERT INTO trip_cities (trip_id, city_id)
        SELECT trip_id, city_id FROM trips
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_trip_cities_city", table_name="trip_cities")
    op.drop_table("trip_cities")
