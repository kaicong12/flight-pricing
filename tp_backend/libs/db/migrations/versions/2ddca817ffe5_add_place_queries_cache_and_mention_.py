"""add place_queries cache and mention category

Revision ID: 2ddca817ffe5
Revises: 80498d35a0df
Create Date: 2026-08-21 11:25:27.074360

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ddca817ffe5'
down_revision: Union[str, Sequence[str], None] = '80498d35a0df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('place_queries',
    sa.Column('city_id', sa.String(length=255), nullable=False),
    sa.Column('query_norm', sa.String(length=200), nullable=False),
    sa.Column('place_id', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['city_id'], ['cities.city_id'], ),
    sa.PrimaryKeyConstraint('city_id', 'query_norm')
    )
    op.add_column('place_mentions', sa.Column('category', sa.String(length=16), nullable=True))
    op.create_check_constraint('ck_category_category', 'place_mentions', "category IN ('see', 'do', 'eat', 'drink', 'buy', 'sleep', 'other')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_category_category', 'place_mentions', type_='check')
    op.drop_column('place_mentions', 'category')
    op.drop_table('place_queries')
