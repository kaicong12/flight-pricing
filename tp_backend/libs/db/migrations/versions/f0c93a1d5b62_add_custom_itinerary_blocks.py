"""add custom itinerary blocks

Revision ID: f0c93a1d5b62
Revises: e5b81c72a9f4
Create Date: 2026-09-26 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f0c93a1d5b62'
down_revision: Union[str, Sequence[str], None] = 'e5b81c72a9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("itinerary_items", sa.Column("kind", sa.String(16), nullable=False,
                                               server_default="place"))
    op.add_column("itinerary_items", sa.Column("block_id", sa.String(36), nullable=True))
    op.add_column("itinerary_items", sa.Column("title", sa.String(120), nullable=True))
    op.add_column("itinerary_items", sa.Column("description", sa.Text(), nullable=True))
    op.alter_column("itinerary_items", "place_id", nullable=True)
    op.create_unique_constraint("uq_itinerary_trip_block", "itinerary_items",
                               ["trip_id", "block_id"])
    op.create_check_constraint("ck_kind_blockkind", "itinerary_items",
                               "kind IN ('place', 'custom')")
    op.create_check_constraint(
        "ck_itinerary_identity", "itinerary_items",
        "(kind = 'place' AND place_id IS NOT NULL AND title IS NULL AND block_id IS NULL) OR "
        "(kind = 'custom' AND title IS NOT NULL AND place_id IS NULL AND block_id IS NOT NULL)")


def downgrade() -> None:
    op.execute("DELETE FROM itinerary_items WHERE kind = 'custom'")
    op.drop_constraint("ck_itinerary_identity", "itinerary_items", type_="check")
    op.drop_constraint("ck_kind_blockkind", "itinerary_items", type_="check")
    op.drop_constraint("uq_itinerary_trip_block", "itinerary_items", type_="unique")
    op.alter_column("itinerary_items", "place_id", nullable=False)
    op.drop_column("itinerary_items", "description")
    op.drop_column("itinerary_items", "title")
    op.drop_column("itinerary_items", "block_id")
    op.drop_column("itinerary_items", "kind")
