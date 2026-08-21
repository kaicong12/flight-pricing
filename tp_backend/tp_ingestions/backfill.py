"""Resolving a finished run's extractions: a free preview, and the enqueue that spends money.

Extraction is cached per (source, source_ref, prompt_version, model), so a run that already
extracted can be resolved without re-scraping or re-prompting anything.
"""

import collections

from libs.db import IngestRun, session
from libs.db.enums import RunStatus, Source, TaskKind
from libs.ingest import enqueue
from tp_ingestions.places import names
from tp_ingestions.places.resolve import candidate_name
from tp_ingestions.runs import run_extractions


def _candidates(s, run_id: str) -> list[tuple]:
    """(source, source_ref, prompt_version, model, name) for every candidate the run extracted."""
    out = []
    for e in s.scalars(run_extractions(s, run_id)).all():
        for place in (e.result or {}).get("places") or []:
            out.append((e.source, e.source_ref, e.prompt_version, e.model,
                        candidate_name(e.source, place), place.get("sentiment")))
    return out


def resolve_preview(run_id: str) -> int:
    """Print what resolution would query and what it would drop. Calls no API."""
    with session() as s:
        if s.get(IngestRun, run_id) is None:
            print(f"no such run: {run_id}")
            return 1

        rows = _candidates(s, run_id)
        keep: dict[str, list[str]] = collections.defaultdict(list)
        dropped: dict[str, list[str]] = collections.defaultdict(list)
        for _, _, _, _, name, sentiment in rows:
            if sentiment == "not_recommended":
                dropped["not recommended by the source"].append(name)
                continue
            reason = names.reject_before_call(name)
            if reason:
                dropped[reason.split(" (")[0]].append(name)
            else:
                keep[names.query_norm(name)].append(name)

        print(f"run {run_id}: {len(rows)} candidate(s) -> {len(keep)} paid searchText call(s)")
        for reason, listed in sorted(dropped.items()):
            print(f"\n  dropped, {reason}: {len(listed)}")
            print(f"    {', '.join(sorted(set(listed)))}")

        merged = {k: v for k, v in keep.items() if len(set(v)) > 1}
        if merged:
            print(f"\n  {len(merged)} key(s) shared by more than one spelling:")
            for key, listed in sorted(merged.items()):
                print(f"    {key:<28} <- {' | '.join(sorted(set(listed)))}")
        print("\n  remaining spelling variants can only be merged by place_id, after the call.")
    return 0


def resolve_run(run_id: str) -> int:
    """Enqueue places.resolve for every extraction the run produced."""
    with session() as s:
        run = s.get(IngestRun, run_id)
        if run is None:
            print(f"no such run: {run_id}")
            return 1
        if not run.city_id:
            print(f"run {run_id} has no city")
            return 1

        seen, rows = set(), []
        for source, ref, version, model, _, _ in _candidates(s, run_id):
            if (source, ref, version) in seen:
                continue
            seen.add((source, ref, version))
            rows.append({
                "run_id": run_id, "kind": TaskKind.PLACES_RESOLVE, "source": Source.PLACES,
                "payload": {"source": source, "source_ref": ref, "prompt_version": version,
                            "model": model, "city_id": run.city_id},
                "dedupe_key": f"{TaskKind.PLACES_RESOLVE}:{source}:{ref}:{version}"})

        queued = enqueue(s, rows)
        if queued:
            # finish_run_if_done only settles a pending/running run, so adding work to a done run
            # without reopening it leaves the tasks finishing and the run stuck on its old status.
            run.status = RunStatus.RUNNING
            run.finished_at = None
        s.commit()

    print(f"{len(rows)} extraction(s) to resolve: queued {queued}, "
          f"{len(rows) - queued} already present")
    if queued:
        print("run reopened as running. Now run: python -m tp_ingestions")
    return 0
