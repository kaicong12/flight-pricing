"""add route.plan task kind

The draft runs as a queued task so it is ready before the user opens the plan screen. TaskKind is a
CHECK constraint, so a new kind is a migration rather than an enum edit alone.

Revision ID: f2b9c07d41ae
Revises: e7a3d5b81c94
Create Date: 2026-09-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f2b9c07d41ae'
down_revision: Union[str, Sequence[str], None] = 'e7a3d5b81c94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = ("youtube.search", "youtube.extract", "rednote.search", "rednote.fetch",
         "rednote.extract", "rednote.ocr", "places.resolve")


def _check(kinds: Sequence[str]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_kind_taskkind", "ingest_tasks", type_="check")
    op.create_check_constraint("ck_kind_taskkind", "ingest_tasks",
                               _check((*KINDS, "route.plan")))


def downgrade() -> None:
    op.execute("DELETE FROM ingest_tasks WHERE kind = 'route.plan'")
    op.drop_constraint("ck_kind_taskkind", "ingest_tasks", type_="check")
    op.create_check_constraint("ck_kind_taskkind", "ingest_tasks", _check(KINDS))
