"""drop unused columns

has_hours was only ever written: _load_hours decides staleness from a row's existence and its
fetched_at, and periods=[] already means "asked, Google publishes none". owner, requested_by and
ip_location were never referenced at all.

Revision ID: e7a3d5b81c94
Revises: d81f2a9c4e57
Create Date: 2026-09-04 04:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a3d5b81c94'
down_revision: Union[str, Sequence[str], None] = 'd81f2a9c4e57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('place_hours', 'has_hours')
    op.drop_column('trips', 'owner')
    op.drop_column('ingest_runs', 'requested_by')
    op.drop_column('rednote_posts', 'ip_location')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('rednote_posts', sa.Column('ip_location', sa.String(length=64), nullable=True))
    op.add_column('ingest_runs', sa.Column('requested_by', sa.String(length=64), nullable=True))
    op.add_column('trips', sa.Column('owner', sa.String(length=64), nullable=True))
    # No default: nothing read it, so backfilling from periods is as good as the original.
    op.add_column('place_hours',
                  sa.Column('has_hours', sa.Boolean(), nullable=False,
                            server_default=sa.text('true')))
    op.execute("UPDATE place_hours SET has_hours = (jsonb_array_length(periods) > 0)")
    op.alter_column('place_hours', 'has_hours', server_default=None)
