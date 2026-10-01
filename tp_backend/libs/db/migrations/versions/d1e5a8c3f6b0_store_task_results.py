"""store what a task's handler returned

Revision ID: d1e5a8c3f6b0
Revises: c8d4e1f7a2b9
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d1e5a8c3f6b0"
down_revision = "c8d4e1f7a2b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_tasks", sa.Column("result", JSONB))


def downgrade() -> None:
    op.drop_column("ingest_tasks", "result")
