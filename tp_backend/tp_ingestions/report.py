"""Read-only summary of one ingest run: what each source yielded, resolved, and what failed."""

from sqlalchemy import func, select

from libs.db import IngestRun, IngestTask, Place, PlaceMention, session
from libs.db.enums import TaskStatus
from tp_ingestions.runs import run_extractions

BAD = (TaskStatus.FAILED, TaskStatus.BLOCKED)


def _rule(title: str) -> str:
    return f"\n{title}\n{'-' * max(len(title), 60)}"


def candidate_lines(place: dict) -> list[str]:
    """One candidate, whichever prompt's shape it came from."""
    name = place.get("name") or place.get("name_as_written") or "?"
    price = place.get("quoted_price") or place.get("spoken_price")
    head = f"    {(place.get('category') or '?').upper():<5} {name}"
    flag = place.get("sentiment")
    if flag and flag != "recommended":
        head += f"  [{flag}]"
    lines = [head]
    if place.get("dish"):
        lines.append(f"          dish: {place['dish']}")
    if price:
        lines.append(f"          price (unverified): {price}")
    if place.get("why_go"):
        lines.append(f"          {place['why_go'][:110]}")
    return lines


def report(run_id: str) -> int:
    """Print the run. Returns a shell exit code: 1 when the run is unknown."""
    with session() as s:
        run = s.get(IngestRun, run_id)
        if run is None:
            print(f"no such run: {run_id}")
            return 1

        print(f"run {run.run_id}  city={run.city_id}  {run.status}  "
              f"failed_tasks={run.failed_task_count}")
        if run.error:
            print(f"  error: {run.error}")

        print(_rule("tasks"))
        counts = s.execute(
            select(IngestTask.kind, IngestTask.status, func.count())
            .where(IngestTask.run_id == run_id)
            .group_by(IngestTask.kind, IngestTask.status).order_by(IngestTask.kind)
        ).all()
        for kind, status, n in counts:
            print(f"  {kind:<18} {status:<10} {n:>3}")

        extractions = s.scalars(run_extractions(s, run_id)).all()
        by_source: dict[str, list] = {}
        for e in extractions:
            by_source.setdefault(e.source, []).append(e)

        for source, rows in by_source.items():
            total = sum(e.place_count for e in rows)
            print(_rule(f"{source}: {len(rows)} extraction(s), {total} candidate(s)"))
            for e in rows:
                result = e.result or {}
                # A wrong-city extraction is the failure mode worth seeing, so lead with the city.
                print(f"  {e.source_ref}  city={result.get('city') or '?'!s:<18} "
                      f"confidence={result.get('city_confidence') or '?':<7} "
                      f"from={e.extracted_from} useful={e.is_useful} "
                      f"promo={e.is_promotional} type={result.get('content_type') or '?'}")
                for place in result.get("places") or []:
                    for line in candidate_lines(place):
                        print(line)

        if run.city_id:
            resolved = s.execute(
                select(Place, func.count(PlaceMention.id))
                .join(PlaceMention, PlaceMention.place_id == Place.place_id)
                .where(Place.city_id == run.city_id)
                .group_by(Place.place_id)
                # Most-mentioned first: that is the ranking signal the mentions exist for.
                .order_by(func.count(PlaceMention.id).desc(), Place.name)
            ).all()
            print(_rule(f"resolved: {len(resolved)} place(s) in {run.city_id}"))
            for place, mentions in resolved:
                print(f"  {mentions:>2}x {place.name:<38} {place.confidence:<7} "
                      f"{place.rating or '-'!s:>4} ({place.rating_count or 0}) "
                      f"{place.primary_type or '-'}")

        bad = s.scalars(
            select(IngestTask).where(IngestTask.run_id == run_id, IngestTask.status.in_(BAD))
            .order_by(IngestTask.task_id)
        ).all()
        if bad:
            print(_rule(f"{len(bad)} task(s) failed or blocked"))
            for t in bad:
                print(f"  {t.kind:<18} {t.status:<8} {t.error_code or '-'}")
                print(f"      {(t.last_error or '').strip()[:220]}")
    return 0
