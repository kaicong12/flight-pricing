"""pin itinerary items to a time

Replaces position with start_min. Travel times were never persisted, so the schedule the old derived
times produced cannot be reproduced — existing rows are dropped rather than given invented times.

Revision ID: d81f2a9c4e57
Revises: c3f81a4e7d12
Create Date: 2026-09-04 04:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd81f2a9c4e57'
down_revision: Union[str, Sequence[str], None] = 'c3f81a4e7d12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM itinerary_items")

    op.add_column('itinerary_items', sa.Column('start_min', sa.Integer(), nullable=False))
    op.drop_index('ix_itinerary_trip_day', table_name='itinerary_items')
    op.drop_constraint('ck_itinerary_position', 'itinerary_items', type_='check')
    op.drop_column('itinerary_items', 'position')

    op.create_check_constraint('ck_itinerary_start', 'itinerary_items',
                               'start_min >= 0 AND start_min < 1440')
    op.drop_constraint('ck_itinerary_duration', 'itinerary_items', type_='check')
    op.create_check_constraint('ck_itinerary_duration', 'itinerary_items',
                               'duration_min >= 30 AND duration_min % 30 = 0')
    op.create_index('ix_itinerary_trip_day', 'itinerary_items',
                    ['trip_id', 'day_index', 'start_min'])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM itinerary_items")

    op.add_column('itinerary_items', sa.Column('position', sa.Integer(), nullable=False))
    op.drop_index('ix_itinerary_trip_day', table_name='itinerary_items')
    op.drop_constraint('ck_itinerary_start', 'itinerary_items', type_='check')
    op.drop_column('itinerary_items', 'start_min')

    op.create_check_constraint('ck_itinerary_position', 'itinerary_items', 'position >= 0')
    op.drop_constraint('ck_itinerary_duration', 'itinerary_items', type_='check')
    op.create_check_constraint('ck_itinerary_duration', 'itinerary_items', 'duration_min > 0')
    op.create_index('ix_itinerary_trip_day', 'itinerary_items',
                    ['trip_id', 'day_index', 'position'])
