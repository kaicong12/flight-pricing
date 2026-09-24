// Mirrors tp_api/plan_schemas.py by hand — there is no codegen step. Warnings arrive as codes; the
// English for them lives here.

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
  city_id: string;
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

/** One venue autocomplete prediction. A label and an id — the rest is fetched when it is picked. */
export type VenueSuggestion = {
  place_id: string;
  name: string;
  context: string | null;
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
  /** The user's own link for this block — a booking, a listing. Never fetched, only opened. */
  reference_url: string | null;
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

export type PlanWarning = {
  code: string;
  place_id: string | null;
  detail: Record<string, string | number>;
};

export type DayRoute = {
  day_index: number;
  date: string;
  /** The first block's time. Null on an empty day. */
  start_time: string | null;
  blocks: PlanBlock[];
  daylight: { sunrise: string; sunset: string } | null;
  warnings: PlanWarning[];
  provisional: string[];
};

/** One block does not work. Phrased as what to do about it, since the user owns the order.
 *
 * `name` is the block the warning is about, prefixed so a list of them says which is which — three
 * warnings that all open "Starts 18:00" are unreadable otherwise. Left off where the caller has no
 * name to give — a day-wide warning names no place. The messages therefore never repeat the name
 * themselves.
 */
export function warningText(w: PlanWarning, name?: string): string {
  const d = w.detail;
  const text = (() => {
    switch (w.code) {
      case "closed":
        return "Closed on this date.";
      case "opens_later":
        return `Pinned ${d.start}, but it opens ${d.opens} — ${d.early_min} min too early.`;
      case "closes_before_done":
        return `Starts ${d.start}, needs ${d.need_min} min, closes ${d.closes}. Move it earlier.`;
      case "after_sunset":
        return `Starts ${d.start}, after sunset at ${d.sunset}. Worth doing in daylight.`;
      case "no_hours":
        return "No opening hours published — unverified.";
      default:
        return w.code;
    }
  })();
  return name ? `${name} — ${text}` : text;
}

/** Whole-plan caveats, as opposed to one broken block. */
export const PROVISIONAL_TEXT: Record<string, string> = {
  regular_hours_only: "regular hours only",
};

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
