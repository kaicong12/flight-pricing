// All of the planning screen's mutable state, as one pure reducer.

import { DEFAULT_DURATION, keyOf } from "@/lib/plan-types";
import type {
  DayRoute,
  Itinerary,
  ItineraryDay,
  ItineraryItem,
  Shortlist,
  ShortlistPlace,
} from "@/lib/plan-types";

export type PlanState = {
  days: ItineraryDay[];
  shortlist: ShortlistPlace[];
  /** Places in the city, before paging. The "9 of 122" denominator. */
  total: number;
  /** `total` with no filter or search applied: what the header counts. */
  found: number;
  dismissed: string[];
  activeDay: number;
  routes: Record<number, DayRoute>;
  /** Edited since it was last checked, so the warnings no longer describe it. */
  stale: number[];
  /** Which days the next write must send. */
  unsaved: number[];
  /** Bumped by every edit. A write carries the revision it saw, so a response that a newer edit has
   *  already superseded can be discarded instead of clobbering it. */
  revision: number;
  savedRevision: number;
};

export type CustomDraft = { title: string; description: string | null };

export type PlanAction =
  | { type: "add"; place: ShortlistPlace; day: number; startMin: number; durationMin: number }
  | { type: "addCustom"; day: number; item: ItineraryItem }
  | { type: "editBlock"; day: number; key: string; draft: CustomDraft }
  | { type: "remove"; day: number; key: string }
  | { type: "pin"; key: string; fromDay: number; toDay: number; startMin: number }
  | { type: "duration"; day: number; key: string; minutes: number }
  | { type: "reference"; day: number; key: string; url: string | null }
  | { type: "activeDay"; day: number }
  | { type: "city"; day: number; cityId: string | null }
  | { type: "dismiss"; placeId: string }
  | { type: "checked"; route: DayRoute }
  | { type: "routeFailed"; day: number }
  | { type: "invalidate"; day: number }
  | { type: "saved"; days: number[]; itinerary: Itinerary; revision: number }
  | { type: "shortlistLoaded"; shortlist: Shortlist; append: boolean; unfiltered?: boolean }
  | { type: "placeAdded"; place: ShortlistPlace; filter?: ShortlistFilter };

export type ShortlistFilter = { category: string | null; source: string | null; q: string };

/** The server's filter, for a place it ranks last and so would page out of sight. */
export function fits(place: ShortlistPlace, filter: ShortlistFilter): boolean {
  const q = filter.q.toLowerCase();
  return (
    !filter.source &&
    (!filter.category || place.category === filter.category) &&
    (!q || [place.name, place.address, place.why_go].some((s) => s?.toLowerCase().includes(q)))
  );
}

const without = (xs: number[], y: number) => xs.filter((x) => x !== y);
const with_ = (xs: number[], y: number) => (xs.includes(y) ? xs : [...xs, y]);

/** The day's sequence, matching how the server reads it back. */
function inTimeOrder(items: ItineraryItem[]): ItineraryItem[] {
  return [...items].sort(
    (a, b) => a.start_min - b.start_min || keyOf(a).localeCompare(keyOf(b)),
  );
}

function setDay(state: PlanState, day: number, items: ItineraryItem[]): ItineraryDay[] {
  return state.days.map((d) => (d.day_index === day ? { ...d, items: inTimeOrder(items) } : d));
}

/** A day whose contents changed needs writing, and its route no longer describes it. */
function touched(
  state: PlanState,
  days: number[],
): Pick<PlanState, "stale" | "unsaved" | "revision"> {
  return {
    stale: days.reduce(with_, state.stale),
    unsaved: days.reduce(with_, state.unsaved),
    revision: state.revision + 1,
  };
}

function itemsOf(state: PlanState, day: number): ItineraryItem[] {
  return state.days.find((d) => d.day_index === day)?.items ?? [];
}

export function itemFor(
  place: ShortlistPlace,
  startMin: number,
  durationMin: number = DEFAULT_DURATION,
): ItineraryItem {
  return {
    kind: "place",
    place_id: place.place_id,
    block_id: crypto.randomUUID(),
    name: place.name,
    description: null,
    lat: place.lat,
    lon: place.lon,
    start_min: startMin,
    duration_min: durationMin,
    category: place.category,
    primary_type: place.primary_type,
    reference_url: null,
  };
}

/** The user's own block. The id is minted here, and is what identifies it from then on. */
export function customItem(
  draft: CustomDraft,
  startMin: number,
  durationMin: number,
): ItineraryItem {
  return {
    kind: "custom",
    place_id: null,
    block_id: crypto.randomUUID(),
    name: draft.title,
    description: draft.description,
    lat: null,
    lon: null,
    start_min: startMin,
    duration_min: durationMin,
    category: null,
    primary_type: null,
    reference_url: null,
  };
}

export function planReducer(state: PlanState, action: PlanAction): PlanState {
  switch (action.type) {
    case "add": {
      const items = [
        ...itemsOf(state, action.day),
        itemFor(action.place, action.startMin, action.durationMin),
      ];
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "addCustom": {
      const items = [...itemsOf(state, action.day), action.item];
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "editBlock": {
      const items = itemsOf(state, action.day).map((i) =>
        keyOf(i) === action.key
          ? { ...i, name: action.draft.title, description: action.draft.description }
          : i,
      );
      return {
        ...state,
        days: setDay(state, action.day, items),
        unsaved: with_(state.unsaved, action.day),
        revision: state.revision + 1,
      };
    }

    case "remove": {
      const items = itemsOf(state, action.day).filter((i) => keyOf(i) !== action.key);
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "pin": {
      const moving = itemsOf(state, action.fromDay).find((i) => keyOf(i) === action.key);
      if (!moving) return state;
      const pinned = { ...moving, start_min: action.startMin };

      if (action.fromDay === action.toDay) {
        if (moving.start_min === action.startMin) return state;
        const items = itemsOf(state, action.toDay).map((i) =>
          keyOf(i) === action.key ? pinned : i,
        );
        return {
          ...state,
          days: setDay(state, action.toDay, items),
          ...touched(state, [action.toDay]),
        };
      }

      const source = itemsOf(state, action.fromDay).filter((i) => keyOf(i) !== action.key);
      const target = [...itemsOf(state, action.toDay), pinned];
      const days = state.days.map((d) => {
        if (d.day_index === action.fromDay) return { ...d, items: inTimeOrder(source) };
        if (d.day_index === action.toDay) return { ...d, items: inTimeOrder(target) };
        return d;
      });
      return { ...state, days, ...touched(state, [action.fromDay, action.toDay]) };
    }

    case "duration": {
      const current = itemsOf(state, action.day).find((i) => keyOf(i) === action.key);
      if (!current || current.duration_min === action.minutes) return state;
      const items = itemsOf(state, action.day).map((i) =>
        keyOf(i) === action.key ? { ...i, duration_min: action.minutes } : i,
      );
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "reference": {
      const current = itemsOf(state, action.day).find((i) => keyOf(i) === action.key);
      if (!current || current.reference_url === action.url) return state;
      const items = itemsOf(state, action.day).map((i) =>
        keyOf(i) === action.key ? { ...i, reference_url: action.url } : i,
      );
      return {
        ...state,
        days: setDay(state, action.day, items),
        unsaved: with_(state.unsaved, action.day),
        revision: state.revision + 1,
      };
    }

    case "activeDay":
      return { ...state, activeDay: action.day };

    case "city":
      return {
        ...state,
        days: state.days.map((d) =>
          d.day_index === action.day ? { ...d, city_id: action.cityId } : d,
        ),
        unsaved: with_(state.unsaved, action.day),
        revision: state.revision + 1,
      };

    case "dismiss":
      return {
        ...state,
        dismissed: with_str(state.dismissed, action.placeId),
        shortlist: state.shortlist.filter((p) => p.place_id !== action.placeId),
        total: Math.max(0, state.total - 1),
        found: Math.max(0, state.found - 1),
      };

    case "checked":
      return {
        ...state,
        routes: { ...state.routes, [action.route.day_index]: action.route },
        stale: without(state.stale, action.route.day_index),
      };

    case "routeFailed":
      return { ...state, stale: without(state.stale, action.day) };

    case "invalidate":
      return { ...state, stale: with_(state.stale, action.day) };

    case "saved": {
      if (action.revision !== state.revision) return state;
      const days = state.days.map(
        (d) => action.itinerary.days.find((x) => x.day_index === d.day_index) ?? d,
      );
      return {
        ...state,
        days,
        unsaved: state.unsaved.filter((d) => !action.days.includes(d)),
        savedRevision: action.revision,
      };
    }

    case "shortlistLoaded":
      return {
        ...state,
        total: action.shortlist.total,
        found: action.unfiltered ? action.shortlist.total : state.found,
        shortlist: action.append
          ? dedupe([...state.shortlist, ...action.shortlist.places])
          : action.shortlist.places,
      };

    case "placeAdded": {
      const known = state.shortlist.some((p) => p.place_id === action.place.place_id);
      const shown = !action.filter || fits(action.place, action.filter);
      return {
        ...state,
        shortlist: shown
          ? dedupe([action.place, ...state.shortlist])
          : state.shortlist.filter((p) => p.place_id !== action.place.place_id),
        dismissed: state.dismissed.filter((id) => id !== action.place.place_id),
        total: shown && !known ? state.total + 1 : state.total,
        found: known ? state.found : state.found + 1,
      };
    }
  }
}

const with_str = (xs: string[], y: string) => (xs.includes(y) ? xs : [...xs, y]);

function dedupe(places: ShortlistPlace[]): ShortlistPlace[] {
  const seen = new Set<string>();
  return places.filter((p) => !seen.has(p.place_id) && seen.add(p.place_id));
}

/** Which day a block sits on, or null. Derived rather than stored, so it cannot drift. */
export function dayOf(state: PlanState, key: string): number | null {
  for (const day of state.days) {
    if (day.items.some((i) => keyOf(i) === key)) return day.day_index;
  }
  return null;
}

/** Only places: this feeds the shortlist's "on day 3" badge, and a flight is on no shortlist. */
export function placedDays(state: PlanState): Map<string, number[]> {
  const out = new Map<string, number[]>();
  for (const day of state.days) {
    for (const item of day.items) {
      if (!item.place_id) continue;
      const days = out.get(item.place_id) ?? [];
      if (!days.includes(day.day_index)) out.set(item.place_id, [...days, day.day_index]);
    }
  }
  return out;
}

export function initialState(
  itinerary: Itinerary,
  shortlist: Shortlist,
): PlanState {
  const firstUsed = itinerary.days.find((d) => d.items.length > 0);
  return {
    days: itinerary.days,
    shortlist: shortlist.places,
    total: shortlist.total,
    found: shortlist.total,
    dismissed: [],
    activeDay: firstUsed?.day_index ?? 0,
    routes: {},
    stale: itinerary.days.filter((d) => d.items.length > 0).map((d) => d.day_index),
    unsaved: [],
    revision: 0,
    savedRevision: 0,
  };
}
