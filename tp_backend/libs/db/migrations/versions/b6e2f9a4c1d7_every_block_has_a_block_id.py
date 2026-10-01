"""every itinerary block has a block_id, so one place may sit on many days

Revision ID: b6e2f9a4c1d7
Revises: d1e5a8c3f6b0
"""

import logging

import sqlalchemy as sa
from alembic import op

log = logging.getLogger("alembic.runtime.migration")

revision = "b6e2f9a4c1d7"
down_revision = "d1e5a8c3f6b0"
branch_labels = None
depends_on = None

OLD_IDENTITY = ("(kind = 'place' AND place_id IS NOT NULL AND title IS NULL AND block_id IS NULL) OR "
                "(kind = 'custom' AND title IS NOT NULL AND place_id IS NULL AND block_id IS NOT NULL)")
NEW_IDENTITY = ("(kind = 'place' AND place_id IS NOT NULL AND title IS NULL) OR "
                "(kind = 'custom' AND title IS NOT NULL AND place_id IS NULL)")


def upgrade() -> None:
    op.drop_constraint("ck_itinerary_identity", "itinerary_items", type_="check")
    op.execute("UPDATE itinerary_items SET block_id = gen_random_uuid()::text "
               "WHERE block_id IS NULL")
    op.alter_column("itinerary_items", "block_id", nullable=False,
                    server_default=sa.text("gen_random_uuid()::text"))
    op.create_check_constraint("ck_itinerary_identity", "itinerary_items", NEW_IDENTITY)
    op.drop_constraint("uq_itinerary_trip_place", "itinerary_items", type_="unique")

    op.execute("""
        UPDATE expenses e SET block_id = i.block_id, place_id = NULL
        FROM itinerary_items i
        WHERE e.place_id IS NOT NULL AND i.trip_id = e.trip_id AND i.place_id = e.place_id
    """)
    orphaned = op.get_bind().scalar(sa.text("SELECT count(*) FROM expenses WHERE place_id IS NOT NULL"))
    if orphaned:
        log.warning("%d cost(s) named a place no longer on its itinerary and lose that link", orphaned)
    op.drop_constraint("ck_expense_block", "expenses", type_="check")
    op.drop_column("expenses", "place_id")


def downgrade() -> None:
    op.add_column("expenses", sa.Column("place_id", sa.String(255),
                                        sa.ForeignKey("places.place_id")))
    op.create_check_constraint("ck_expense_block", "expenses",
                               "place_id IS NULL OR block_id IS NULL")

    op.execute("""
        UPDATE expenses e SET place_id = i.place_id, block_id = NULL
        FROM itinerary_items i
        WHERE i.trip_id = e.trip_id AND i.block_id = e.block_id AND i.place_id IS NOT NULL
    """)
    # Only one copy of a place survives; the earliest is kept and the rest are lost.
    op.execute("""
        DELETE FROM itinerary_items i USING itinerary_items keep
        WHERE i.place_id IS NOT NULL AND keep.trip_id = i.trip_id AND keep.place_id = i.place_id
          AND (keep.day_index, keep.start_min, keep.id) < (i.day_index, i.start_min, i.id)
    """)
    op.create_unique_constraint("uq_itinerary_trip_place", "itinerary_items",
                                ["trip_id", "place_id"])
    op.drop_constraint("ck_itinerary_identity", "itinerary_items", type_="check")
    op.alter_column("itinerary_items", "block_id", nullable=True, server_default=None)
    op.execute("UPDATE itinerary_items SET block_id = NULL WHERE kind = 'place'")
    op.create_check_constraint("ck_itinerary_identity", "itinerary_items", OLD_IDENTITY)
