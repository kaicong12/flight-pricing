"""add itinerary_items.reference_url

Revision ID: b17c4e90d2f5
Revises: a4c218de90b3
Create Date: 2026-09-21 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b17c4e90d2f5'
down_revision: Union[str, Sequence[str], None] = 'a4c218de90b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('itinerary_items', sa.Column('reference_url', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('itinerary_items', 'reference_url')
