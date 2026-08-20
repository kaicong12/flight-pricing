"""add trips, widen city keys to place_id

Revision ID: b1c4d7e29f83
Revises: 0aa60702698f
Create Date: 2026-08-20 11:14:02.118433

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1c4d7e29f83'
down_revision: Union[str, Sequence[str], None] = '0aa60702698f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Postgres keeps a foreign key valid while both sides stay varchar, so these widen independently
# and need no constraint drops.
CITY_KEY_COLUMNS = [("cities", "city_id"), ("places", "city_id"), ("ingest_runs", "city_id")]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in CITY_KEY_COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(length=64),
                        type_=sa.String(length=255))

    op.add_column('cities', sa.Column('timezone', sa.String(length=64), nullable=True))

    op.alter_column('ingest_tasks', 'dedupe_key', existing_type=sa.String(length=255),
                    type_=sa.String(length=512))
    op.alter_column('ingest_runs', 'status', existing_type=sa.String(length=20),
                    server_default=sa.text("'pending'"))
    op.create_check_constraint('ck_extracted_from_extractedfrom', 'extractions',
                               "extracted_from IN ('text', 'image')")

    op.create_table('trips',
    sa.Column('trip_id', sa.String(length=36), nullable=False),
    sa.Column('city_id', sa.String(length=255), nullable=False),
    sa.Column('arrive_date', sa.Date(), nullable=False),
    sa.Column('arrive_time', sa.Time(), nullable=True),
    sa.Column('depart_date', sa.Date(), nullable=False),
    sa.Column('depart_time', sa.Time(), nullable=True),
    sa.Column('extra_details', sa.Text(), nullable=True),
    sa.Column('owner', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('depart_date >= arrive_date', name='ck_trip_dates'),
    sa.ForeignKeyConstraint(['city_id'], ['cities.city_id'], ),
    sa.PrimaryKeyConstraint('trip_id')
    )
    op.create_index('ix_trips_city', 'trips', ['city_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_trips_city', table_name='trips')
    op.drop_table('trips')

    op.drop_constraint('ck_extracted_from_extractedfrom', 'extractions', type_='check')
    op.alter_column('ingest_runs', 'status', existing_type=sa.String(length=20),
                    server_default=None)
    op.alter_column('ingest_tasks', 'dedupe_key', existing_type=sa.String(length=512),
                    type_=sa.String(length=255))

    op.drop_column('cities', 'timezone')

    # Fails if any id is longer than 64 characters, which real place_ids are not.
    for table, column in reversed(CITY_KEY_COLUMNS):
        op.alter_column(table, column, existing_type=sa.String(length=255),
                        type_=sa.String(length=64))
