// Mirrors tp_api/plan_schemas.py by hand — there is no codegen step. Warnings arrive as codes; the
// English for them lives here.

export type TravelMode = "walk" | "transit";

// The grid a block is dragged against. Must match SLOT_MIN in tp_api/plan_schemas.py and the
// ck_itinerary_duration CHECK, or the server rejects what the user just dragged.
export const SLOT_MIN = 30;
export const MIN_DURATION = SLOT_MIN;
export const DEFAULT_DURATION = 60;

// The visible day. Wide enough for an early start and a late dinner without scrolling all night.
export const DAY_START_MIN = 8 * 60;
export const DAY_END_MIN = 23 * 60;

export type SourceRef = {
  source: string;
  title: string;
  url: string;
};

export type ShortlistPlace = {
  place_id: string;
  name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  primary_type: string | null;
  category: string | null;
  why_go: string | null;
  sources: SourceRef[];
  mention_count: number;
  in_itinerary: boolean;
  day_index: number | null;
};

export type Shortlist = {
  total: number;
  shown: number;
  places: ShortlistPlace[];
};

export type ItineraryItem = {
  place_id: string;
  name: string;
  lat: number | null;
  lon: number | null;
  /** Local minutes past midnight. The user's statement, never derived. */
  start_min: number;
  duration_min: number;
  category: string | null;
  primary_type: string | null;
};

export type ItineraryDay = {
  day_index: number;
  date: string;
  items: ItineraryItem[];
};

export type Itinerary = { days: ItineraryDay[] };

export type PlanBlock = {
  place_id: string;
  name: string;
  start: string;
  end: string;
  duration_min: number;
  open_from: string | null;
  open_to: string | null;
};

export type PlanLeg = {
  from_place_id: string;
  to_place_id: string;
  seconds: number;
  meters: number;
  transit_steps: string[];
  polyline: string | null;
};

export type PlanWarning = {
  code: string;
  place_id: string | null;
  detail: Record<string, string | number>;
};

export type DayRoute = {
  day_index: number;
  date: string;
  mode: TravelMode;
  /** The first block's time. Null on an empty day. */
  start_time: string | null;
  blocks: PlanBlock[];
  legs: PlanLeg[];
  polyline: string | null;
  total_distance_m: number;
  total_travel_s: number;
  routed: boolean;
  daylight: { sunrise: string; sunset: string } | null;
  warnings: PlanWarning[];
  provisional: string[];
};

/** One block does not work. Phrased as what to do about it, since the user owns the order. */
export function warningText(w: PlanWarning): string {
  const d = w.detail;
  switch (w.code) {
    case "closed":
      return `${d.name} is closed on this date.`;
    case "opens_later":
      return `Pinned ${d.start}, but it opens ${d.opens} — ${d.early_min} min too early.`;
    case "closes_before_done":
      return `Starts ${d.start}, needs ${d.need_min} min, closes ${d.closes}. Move it earlier.`;
    case "travel_does_not_fit":
      return Number(d.gap_min) < 0
        ? `Overlaps ${d.from}, and the ${d.need_min} min trip between them is not possible.`
        : `Only ${d.gap_min} min after ${d.from}, but it is a ${d.need_min} min trip.`;
    case "after_sunset":
      return `Starts ${d.start}, after sunset at ${d.sunset}. Worth doing in daylight.`;
    case "no_hours":
      return `No opening hours published for ${d.name} — unverified.`;
    case "no_route":
      return d.from
        ? `No route found from ${d.from} to ${d.to}.`
        : "No travel times available, so these times ignore getting between places.";
    case "implausible_leg":
      return `The ${d.kmh} km/h leg to ${d.to} probably crosses water on a scheduled boat — check the timetable, the time shown assumes no wait.`;
    default:
      return w.code;
  }
}

/** Whole-plan caveats, as opposed to one broken block. */
export const PROVISIONAL_TEXT: Record<string, string> = {
  transit_horizon: "walking times only",
  regular_hours_only: "regular hours only",
};

export function formatDistance(meters: number): string {
  return meters < 1000 ? `${meters} m` : `${(meters / 1000).toFixed(1)} km`;
}

export function formatMinutes(seconds: number): string {
  return `${Math.round(seconds / 60)} min`;
}

/** "Thu 4 Dec" — the day tabs. */
export function formatDayTab(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/**
 * The window a day's blocks must fit inside. The flight is the only hard bound there is: you cannot
 * be somewhere before you land or after you leave, so those minutes are not offered at all.
 *
 * Mirrors _available_window in tp_api/plan_routes.py, which rejects anything outside it.
 */
export function availableWindow(
  trip: { arrive_time: string | null; depart_time: string | null },
  dayIndex: number,
  dayCount: number,
): { from: number; to: number } {
  const mins = (t: string | null) => {
    if (!t) return null;
    const [h, m] = t.split(":");
    return Number(h) * 60 + Number(m);
  };
  const arrive = dayIndex === 0 ? mins(trip.arrive_time) : null;
  const depart = dayIndex === dayCount - 1 ? mins(trip.depart_time) : null;
  return { from: arrive ?? 0, to: depart ?? 24 * 60 };
}

/** Minutes past midnight as HH:MM, wrapping a block that runs past midnight. */
export function hhmm(min: number): string {
  const m = Math.round(min);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export const endOf = (i: ItineraryItem) => i.start_min + i.duration_min;

export function snap(min: number): number {
  return Math.round(min / SLOT_MIN) * SLOT_MIN;
}

/** Pixel offset inside the grid to a snapped start time. */
export function slotAt(offsetPx: number, slotPx: number): number {
  return DAY_START_MIN + snap((offsetPx / slotPx) * SLOT_MIN);
}

/**
 * Resize by dragging an edge. The moving edge snaps; the opposite edge never moves, which is what
 * stops a top-drag from walking the whole block down the grid.
 */
export function resize(
  item: ItineraryItem,
  edge: "top" | "bottom",
  toMin: number,
): { start_min: number; duration_min: number } {
  if (edge === "bottom") {
    const end = Math.max(item.start_min + MIN_DURATION, Math.min(snap(toMin), DAY_END_MIN));
    return { start_min: item.start_min, duration_min: end - item.start_min };
  }
  const end = endOf(item);
  const start = Math.min(end - MIN_DURATION, Math.max(snap(toMin), DAY_START_MIN));
  return { start_min: start, duration_min: end - start };
}

export type PlacedItem = { item: ItineraryItem; lane: number; lanes: number };

/**
 * Lane assignment for overlapping blocks, the calendar layout. Blocks are grouped into clusters that
 * transitively overlap, and `lanes` is the cluster's width — so two overlapping blocks are each half
 * width even when a third sits alone above them.
 */
export function layout(items: ItineraryItem[]): PlacedItem[] {
  const sorted = [...items].sort(
    (a, b) => a.start_min - b.start_min || a.place_id.localeCompare(b.place_id),
  );
  const out: PlacedItem[] = [];
  let cluster: PlacedItem[] = [];
  let clusterEnd = -Infinity;

  const flush = () => {
    const lanes = cluster.reduce((n, p) => Math.max(n, p.lane + 1), 0);
    for (const p of cluster) out.push({ ...p, lanes });
    cluster = [];
    clusterEnd = -Infinity;
  };

  for (const item of sorted) {
    if (item.start_min >= clusterEnd) flush();
    const laneEnds: number[] = [];
    for (const p of cluster) {
      laneEnds[p.lane] = Math.max(laneEnds[p.lane] ?? -Infinity, endOf(p.item));
    }
    let lane = laneEnds.findIndex((end) => end <= item.start_min);
    if (lane === -1) lane = laneEnds.length === 0 ? 0 : laneEnds.length;
    cluster.push({ item, lane, lanes: 1 });
    clusterEnd = Math.max(clusterEnd, endOf(item));
  }
  flush();
  return out;
}

/** "14:20" from tp_api's "14:20:00". */
export function shortTime(t: string | null): string | null {
  return t ? t.slice(0, 5) : null;
}
