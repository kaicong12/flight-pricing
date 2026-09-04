// THROWAWAY SPIKE: the pure half-hour-grid maths behind a calendar day.
//
// No React, no DOM — `npx tsx slots.check.ts` exercises all of it. Every decision lives here: all
// items are pinned, overlaps are allowed and laid out in lanes, and travel that does not fit is
// reported and never silently fixed.

export const SLOT_MIN = 30;
export const MIN_DURATION = SLOT_MIN;
export const DEFAULT_DURATION = 60;

export type Stop = {
  id: string;
  name: string;
  startMin: number;
  durationMin: number;
  openFrom?: number | null;
  openTo?: number | null;
  outdoor?: boolean;
};

export type Placed = Stop & { lane: number; lanes: number };

export type Conflict =
  | { code: "travel_does_not_fit"; id: string; fromId: string; needMin: number; gapMin: number }
  | { code: "opens_later"; id: string; opensAt: number; waitMin: number }
  | { code: "closes_before_done"; id: string; closesAt: number }
  | { code: "after_sunset"; id: string; sunsetMin: number }
  | { code: "outside_day"; id: string };

export const endOf = (s: Stop) => s.startMin + s.durationMin;

/** Nearest half hour. Used for both a drop and a resize, so they can never disagree. */
export function snap(min: number): number {
  return Math.round(min / SLOT_MIN) * SLOT_MIN;
}

/** Pixel offset inside the grid -> a snapped start time. */
export function slotAt(offsetPx: number, dayStartMin: number, slotPx: number): number {
  return dayStartMin + snap((offsetPx / slotPx) * SLOT_MIN);
}

export function topPx(startMin: number, dayStartMin: number, slotPx: number): number {
  return ((startMin - dayStartMin) / SLOT_MIN) * slotPx;
}

export function heightPx(durationMin: number, slotPx: number): number {
  return (durationMin / SLOT_MIN) * slotPx;
}

/**
 * Resize by dragging an edge. The moving edge snaps; the opposite edge never moves, which is what
 * stops a top-drag from walking the whole box down the grid.
 */
export function resize(stop: Stop, edge: "top" | "bottom", toMin: number): Stop {
  if (edge === "bottom") {
    const end = Math.max(stop.startMin + MIN_DURATION, snap(toMin));
    return { ...stop, durationMin: end - stop.startMin };
  }
  const end = endOf(stop);
  const start = Math.min(end - MIN_DURATION, snap(toMin));
  return { ...stop, startMin: start, durationMin: end - start };
}

/**
 * Lane assignment for overlapping stops, the Google Calendar layout.
 *
 * Stops are grouped into clusters that transitively overlap, and `lanes` is the cluster's width —
 * so two overlapping boxes are each half width even when a third sits alone above them.
 */
export function layout(stops: Stop[]): Placed[] {
  const sorted = [...stops].sort((a, b) => a.startMin - b.startMin || a.id.localeCompare(b.id));
  const out: Placed[] = [];

  let cluster: Placed[] = [];
  let clusterEnd = -Infinity;

  const flush = () => {
    const lanes = cluster.reduce((n, s) => Math.max(n, s.lane + 1), 0);
    for (const s of cluster) out.push({ ...s, lanes });
    cluster = [];
    clusterEnd = -Infinity;
  };

  for (const stop of sorted) {
    if (stop.startMin >= clusterEnd) flush();

    // Lowest lane whose current occupant has already finished.
    const laneEnds: number[] = [];
    for (const s of cluster) laneEnds[s.lane] = Math.max(laneEnds[s.lane] ?? -Infinity, endOf(s));
    let lane = laneEnds.findIndex((end) => end <= stop.startMin);
    if (lane === -1) lane = laneEnds.length === 0 ? 0 : laneEnds.length;

    cluster.push({ ...stop, lane, lanes: 1 });
    clusterEnd = Math.max(clusterEnd, endOf(stop));
  }
  flush();

  return out;
}

/**
 * Everything wrong with the day, in the user's own times. Nothing is moved — this is the whole
 * point of pinning, and it mirrors what libs/routing/plan.py does on the server.
 *
 * `travelMin(a, b)` is the real leg from computeRoutes; the prototype fakes it.
 */
export function conflicts(
  stops: Stop[],
  travelMin: (fromId: string, toId: string) => number,
  { dayStartMin, dayEndMin, sunsetMin }: {
    dayStartMin: number;
    dayEndMin: number;
    sunsetMin?: number | null;
  },
): Conflict[] {
  const sorted = [...stops].sort((a, b) => a.startMin - b.startMin || a.id.localeCompare(b.id));
  const found: Conflict[] = [];

  for (const [i, s] of sorted.entries()) {
    if (s.startMin < dayStartMin || endOf(s) > dayEndMin) {
      found.push({ code: "outside_day", id: s.id });
    }
    if (s.openFrom != null && s.startMin < s.openFrom) {
      found.push({
        code: "opens_later", id: s.id, opensAt: s.openFrom, waitMin: s.openFrom - s.startMin,
      });
    }
    if (s.openTo != null && endOf(s) > s.openTo) {
      found.push({ code: "closes_before_done", id: s.id, closesAt: s.openTo });
    }
    if (s.outdoor && sunsetMin != null && s.startMin > sunsetMin) {
      found.push({ code: "after_sunset", id: s.id, sunsetMin });
    }

    // Against the previous stop by time, which under overlaps is not the previous by lane.
    const prev = sorted[i - 1];
    if (prev) {
      const needMin = travelMin(prev.id, s.id);
      const gapMin = s.startMin - endOf(prev);
      if (needMin > gapMin) {
        found.push({
          code: "travel_does_not_fit", id: s.id, fromId: prev.id, needMin, gapMin,
        });
      }
    }
  }
  return found;
}

export function hhmm(min: number): string {
  const m = Math.round(min);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
