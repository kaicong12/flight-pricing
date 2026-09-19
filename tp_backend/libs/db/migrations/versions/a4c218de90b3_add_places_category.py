"""add places.category

Revision ID: a4c218de90b3
Revises: c551f84a2e7d
Create Date: 2026-09-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c218de90b3'
down_revision: Union[str, Sequence[str], None] = 'c551f84a2e7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('places', sa.Column('category', sa.String(length=16), nullable=True))
    op.create_check_constraint(
        'ck_category_category', 'places',
        "category IN ('see', 'do', 'eat', 'drink', 'buy', 'sleep', 'other')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_category_category', 'places', type_='check')
    op.drop_column('places', 'category')
