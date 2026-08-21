"""Reading a run's extractions back.

Extractions are keyed on (source, source_ref, prompt_version, model) and deliberately carry no
run_id — a note is extracted once and reused across runs. So the way back from a run to its
extractions is through the source refs its tasks named.
"""

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from libs.db import Extraction, IngestTask

# Whichever key a task kind uses for the thing it processed.
_REF_KEYS = ("note_id", "video_id")


def run_source_refs(session: Session, run_id: str) -> set[str]:
    """Every source ref the run's tasks touched."""
    refs = set()
    for key in _REF_KEYS:
        refs |= set(session.scalars(
            select(IngestTask.payload[key].as_string())
            .where(IngestTask.run_id == run_id, IngestTask.payload[key].as_string().is_not(None))
        ).all())
    return refs


def run_extractions(session: Session, run_id: str) -> Select:
    """Select the run's extractions, in a stable order."""
    refs = run_source_refs(session, run_id)
    if not refs:
        # An empty IN would match everything, which is how report() came to print the whole database.
        return select(Extraction).where(or_(False))
    return (select(Extraction).where(Extraction.source_ref.in_(refs))
            .order_by(Extraction.source, Extraction.source_ref, Extraction.prompt_version))
