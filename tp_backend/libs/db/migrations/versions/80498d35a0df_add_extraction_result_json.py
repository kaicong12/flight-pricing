"""add extraction result json

Revision ID: 80498d35a0df
Revises: b1c4d7e29f83
Create Date: 2026-08-20 14:43:47.916252

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '80498d35a0df'
down_revision: Union[str, Sequence[str], None] = 'b1c4d7e29f83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('extractions',
                  sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('extractions', 'result')
