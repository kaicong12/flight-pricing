"""add trips.name

Revision ID: c3f81a4e7d12
Revises: 6faab6b6e804
Create Date: 2026-09-04 01:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f81a4e7d12'
down_revision: Union[str, Sequence[str], None] = '6faab6b6e804'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('trips', sa.Column('name', sa.String(length=120), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('trips', 'name')
