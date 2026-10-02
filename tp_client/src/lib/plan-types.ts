// Mirrors tp_api/route_planning/schemas.py by hand — there is no codegen step. Warnings arrive as codes; the
// English for them lives here.

// The grid a block is dragged against. A typed time may be any minute; a drag snaps to this.
export const SLOT_MIN = 30;
export const MIN_DURATION = SLOT_MIN;
export const DEFAULT_DURATION = 60;

export const DAY_START_MIN = 0;
export const DAY_END_MIN = 24 * 60;

/** tp_backend's Source enum: where a mention came from. */
export type ShortlistSource = "youtube" | "rednote";

export type SourceRef = {
  source: string;
  title: string;
  url: string;
};

export type ShortlistPlace = {
  place_id: string;
  /** The city this place is genuinely in. Null on a one-city trip, or when tp_api cannot say. */
  city_name: string | null;
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

/** A venue from the shortlist, or the user's own entry — a flight, a stay, a booked activity. */
export type BlockKind = "place" | "custom";

export type ItineraryItem = {
  kind: BlockKind;
  place_id: string | null;
  /** Every block's identity, minted here. */
  block_id: string;
  name: string;
  /** Free text on a custom block: the flight number, the hotel address, the pickup point. */
  description: string | null;
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

/** What identifies a block on screen and in the reducer. */
export const keyOf = (i: { block_id: string }) => i.block_id;

export type ItineraryDay = {
  day_index: number;
  date: string;
  items: ItineraryItem[];
};

export type Itinerary = { days: ItineraryDay[] };

export type PlanBlock = {
  kind: BlockKind;
  place_id: string | null;
  block_id: string;
  name: string;
  description: string | null;
  start: string;
  end: string;
  duration_min: number;
  open_from: string | null;
  open_to: string | null;
};

export type PlanWarning = {
  code: string;
  place_id: string | null;
  block_id: string | null;
  detail: Record<string, string | number>;
};

export type DayRoute = {
  day_index: number;
  date: string;
  /** The first block's time. Null on an empty day. */
  start_time: string | null;
  blocks: PlanBlock[];
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
 * Mirrors available_window in tp_api/route_planning/utils.py, which rejects anything outside it.
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
 * stops a top-drag from walking the whole block down the grid. `offset` is how many minutes after
 * the block's own day the grid being dragged on starts, for the last day of a multi-day block.
 */
export function resize(
  item: ItineraryItem,
  edge: "top" | "bottom",
  toMin: number,
  offset = 0,
): { start_min: number; duration_min: number } {
  if (edge === "bottom") {
    const end = Math.max(
      item.start_min + MIN_DURATION,
      offset + Math.min(snap(toMin), DAY_END_MIN),
    );
    return { start_min: item.start_min, duration_min: end - item.start_min };
  }
  const end = endOf(item);
  const start = Math.min(end - MIN_DURATION, Math.max(snap(toMin), DAY_START_MIN));
  return { start_min: start, duration_min: end - start };
}

/** One day's share of a block: `from`/`to` in that day's minutes, `offset` past the block's day. */
export type Piece = { item: ItineraryItem; offset: number; from: number; to: number };

/** Every block that reaches this day, including the tail of one that started on an earlier day. */
export function piecesOn(days: ItineraryDay[], dayIndex: number): Piece[] {
  const out: Piece[] = [];
  for (const d of days) {
    const offset = (dayIndex - d.day_index) * DAY_END_MIN;
    if (offset < 0) continue;
    for (const item of d.items) {
      const from = Math.max(0, item.start_min - offset);
      const to = Math.min(DAY_END_MIN, endOf(item) - offset);
      if (to > from) out.push({ item, offset, from, to });
    }
  }
  return out;
}

const MORNING_MIN = 9 * 60;

/** Where a new block on this day should start: the first free half hour from 09:00, then earlier. */
export function firstFree(pieces: Piece[], window: { from: number; to: number }): number | null {
  const from = Math.ceil(window.from / SLOT_MIN) * SLOT_MIN;
  const morning = Math.max(from, MORNING_MIN);
  const starts: number[] = [];
  for (let m = morning; m < window.to; m += SLOT_MIN) starts.push(m);
  for (let m = from; m < morning; m += SLOT_MIN) starts.push(m);
  for (const length of [60, MIN_DURATION]) {
    const fit = starts.find(
      (m) => m + length <= window.to && !pieces.some((p) => m < p.to && p.from < m + length),
    );
    if (fit !== undefined) return fit;
  }
  return null;
}

/** The day a block ends on, and the minute it ends there. Midnight belongs to the day before. */
export function endsOn(item: ItineraryItem, dayIndex: number): { day: number; min: number } {
  const extra = Math.max(0, Math.ceil(endOf(item) / DAY_END_MIN) - 1);
  return { day: dayIndex + extra, min: endOf(item) - extra * DAY_END_MIN };
}

export type PlacedItem = { item: ItineraryItem; lane: number; lanes: number };

/**
 * Lane assignment for overlapping blocks, the calendar layout. Blocks are grouped into clusters that
 * transitively overlap, and `lanes` is the cluster's width — so two overlapping blocks are each half
 * width even when a third sits alone above them.
 */
export function layout(items: ItineraryItem[]): PlacedItem[] {
  const sorted = [...items].sort(
    (a, b) => a.start_min - b.start_min || keyOf(a).localeCompare(keyOf(b)),
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
