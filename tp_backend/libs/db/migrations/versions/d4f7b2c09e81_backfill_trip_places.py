"""backfill trip_places

Revision ID: d4f7b2c09e81
Revises: c2e4a91b7d30
Create Date: 2026-09-22 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4f7b2c09e81'
down_revision: Union[str, Sequence[str], None] = 'c2e4a91b7d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A claim is now the whole shortlist, so every trip must claim what its city already gave it.

    Soft-deleted trips included: this preserves what each trip could already see, and `deleted`
    decides what is listed rather than what a trip owns.
    """
    op.execute("""
        INSERT INTO trip_places (trip_id, place_id)
        SELECT t.trip_id, p.place_id FROM trips t JOIN places p ON p.city_id = t.city_id
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    """Nothing: a backfilled claim is indistinguishable from a hand-added one, and restoring the
    city-wide predicate makes the difference stop mattering."""
