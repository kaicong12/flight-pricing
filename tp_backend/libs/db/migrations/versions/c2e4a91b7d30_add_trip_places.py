"""add trip_places

Revision ID: c2e4a91b7d30
Revises: b17c4e90d2f5
Create Date: 2026-09-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2e4a91b7d30'
down_revision: Union[str, Sequence[str], None] = 'b17c4e90d2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'trip_places',
        sa.Column('trip_id', sa.String(length=36), nullable=False),
        sa.Column('place_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.trip_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['place_id'], ['places.place_id']),
        sa.PrimaryKeyConstraint('trip_id', 'place_id'),
    )
    # Hand-added places were city-scoped until now, and the shortlist no longer reaches them that
    # way. A set category is what marks them; claim each one for every trip in its city.
    op.execute("""
        INSERT INTO trip_places (trip_id, place_id)
        SELECT t.trip_id, p.place_id
        FROM trips t
        JOIN places p ON p.city_id = t.city_id
        WHERE p.category IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('trip_places')
