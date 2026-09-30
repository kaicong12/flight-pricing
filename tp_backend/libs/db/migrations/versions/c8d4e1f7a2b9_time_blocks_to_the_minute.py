"""time itinerary blocks to the minute

Revision ID: c8d4e1f7a2b9
Revises: b7c2e91d04a8
"""

from alembic import op

revision = "c8d4e1f7a2b9"
down_revision = "b7c2e91d04a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_itinerary_duration", "itinerary_items", type_="check")
    op.create_check_constraint("ck_itinerary_duration", "itinerary_items", "duration_min > 0")


def downgrade() -> None:
    op.drop_constraint("ck_itinerary_duration", "itinerary_items", type_="check")
    op.create_check_constraint("ck_itinerary_duration", "itinerary_items",
                               "duration_min >= 30 AND duration_min % 30 = 0")
