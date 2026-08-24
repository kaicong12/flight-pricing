// All of the planning screen's mutable state, as one pure reducer.
//
// A reducer rather than a dozen useStates because the transitions are interdependent: moving a place
// changes two days, renumbers both, marks both unsaved and both un-routed. Doing that in one place
// is what stops a half-applied drag.

import type {
  DayRoute,
  Itinerary,
  ItineraryDay,
  ItineraryItem,
  Shortlist,
  ShortlistPlace,
  TravelMode,
} from "@/lib/plan-types";

export type PlanState = {
  days: ItineraryDay[];
  shortlist: ShortlistPlace[];
  /** Places in the city, before paging. The "9 of 122" denominator. */
  total: number;
  dismissed: string[];
  activeDay: number;
  mode: TravelMode;
  routes: Record<number, DayRoute>;
  /** Reordered since it was last routed, so its times no longer describe it. */
  stale: number[];
  /** Which days the next write must send. */
  unsaved: number[];
  /** Bumped by every edit. A write carries the revision it saw, so a response that a newer edit has
   *  already superseded can be discarded instead of clobbering it. */
  revision: number;
  savedRevision: number;
};

export type PlanAction =
  | { type: "add"; place: ShortlistPlace; day: number }
  | { type: "remove"; day: number; placeId: string }
  | { type: "reorder"; day: number; from: number; to: number }
  | { type: "move"; placeId: string; fromDay: number; toDay: number; toIndex: number }
  | { type: "duration"; day: number; placeId: string; minutes: number }
  | { type: "activeDay"; day: number }
  | { type: "mode"; mode: TravelMode }
  | { type: "dismiss"; placeId: string }
  | { type: "routed"; route: DayRoute }
  | { type: "routeFailed"; day: number }
  | { type: "invalidate"; day: number }
  | { type: "saved"; days: number[]; itinerary: Itinerary; revision: number }
  | { type: "shortlistLoaded"; shortlist: Shortlist; append: boolean };

const without = (xs: number[], y: number) => xs.filter((x) => x !== y);
const with_ = (xs: number[], y: number) => (xs.includes(y) ? xs : [...xs, y]);

/** Positions are dense and derived, never carried across an edit. */
function renumber(items: ItineraryItem[]): ItineraryItem[] {
  return items.map((item, position) => (item.position === position ? item : { ...item, position }));
}

function setDay(state: PlanState, day: number, items: ItineraryItem[]): ItineraryDay[] {
  return state.days.map((d) => (d.day_index === day ? { ...d, items: renumber(items) } : d));
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

export function itemFor(place: ShortlistPlace, position: number): ItineraryItem {
  return {
    place_id: place.place_id,
    name: place.name,
    lat: place.lat,
    lon: place.lon,
    position,
    duration_min: place.default_duration_min,
    category: place.category,
    primary_type: place.primary_type,
  };
}

export function planReducer(state: PlanState, action: PlanAction): PlanState {
  switch (action.type) {
    case "add": {
      // A place sits on at most one day, so adding one already placed is a move.
      const current = dayOf(state, action.place.place_id);
      if (current !== null) {
        return planReducer(state, {
          type: "move",
          placeId: action.place.place_id,
          fromDay: current,
          toDay: action.day,
          toIndex: itemsOf(state, action.day).length,
        });
      }
      const items = [...itemsOf(state, action.day), itemFor(action.place, 0)];
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "remove": {
      const items = itemsOf(state, action.day).filter((i) => i.place_id !== action.placeId);
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "reorder": {
      const items = [...itemsOf(state, action.day)];
      if (action.from === action.to) return state;
      const [moved] = items.splice(action.from, 1);
      if (!moved) return state;
      items.splice(action.to, 0, moved);
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "move": {
      if (action.fromDay === action.toDay) {
        const from = itemsOf(state, action.fromDay).findIndex(
          (i) => i.place_id === action.placeId,
        );
        return from < 0
          ? state
          : planReducer(state, {
              type: "reorder",
              day: action.fromDay,
              from,
              to: action.toIndex,
            });
      }
      const moving = itemsOf(state, action.fromDay).find((i) => i.place_id === action.placeId);
      if (!moving) return state;
      const source = itemsOf(state, action.fromDay).filter((i) => i.place_id !== action.placeId);
      const target = [...itemsOf(state, action.toDay)];
      target.splice(Math.min(action.toIndex, target.length), 0, moving);
      const days = state.days.map((d) => {
        if (d.day_index === action.fromDay) return { ...d, items: renumber(source) };
        if (d.day_index === action.toDay) return { ...d, items: renumber(target) };
        return d;
      });
      return { ...state, days, ...touched(state, [action.fromDay, action.toDay]) };
    }

    case "duration": {
      const items = itemsOf(state, action.day).map((i) =>
        i.place_id === action.placeId ? { ...i, duration_min: action.minutes } : i,
      );
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "activeDay":
      return { ...state, activeDay: action.day };

    // Changing mode invalidates every computed route, not just the visible one.
    case "mode":
      return { ...state, mode: action.mode, routes: {}, stale: state.days.map((d) => d.day_index) };

    case "dismiss":
      return {
        ...state,
        dismissed: with_str(state.dismissed, action.placeId),
        shortlist: state.shortlist.filter((p) => p.place_id !== action.placeId),
        total: Math.max(0, state.total - 1),
      };

    case "routed":
      return {
        ...state,
        routes: { ...state.routes, [action.route.day_index]: action.route },
        stale: without(state.stale, action.route.day_index),
      };

    // Drop the stale marker so a failing day does not re-request on every render.
    case "routeFailed":
      return { ...state, stale: without(state.stale, action.day) };

    // What "Re-route day" asks for: bin the answer we have and go again.
    case "invalidate":
      return { ...state, stale: with_(state.stale, action.day) };

    // A write landed. If the user has edited since, the response describes an older plan than the
    // one on screen, so it is dropped rather than reverting their last drag.
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
        shortlist: action.append
          ? dedupe([...state.shortlist, ...action.shortlist.places])
          : action.shortlist.places,
      };
  }
}

const with_str = (xs: string[], y: string) => (xs.includes(y) ? xs : [...xs, y]);

function dedupe(places: ShortlistPlace[]): ShortlistPlace[] {
  const seen = new Set<string>();
  return places.filter((p) => !seen.has(p.place_id) && seen.add(p.place_id));
}

/** Which day a place sits on, or null. Derived rather than stored, so it cannot drift. */
export function dayOf(state: PlanState, placeId: string): number | null {
  for (const day of state.days) {
    if (day.items.some((i) => i.place_id === placeId)) return day.day_index;
  }
  return null;
}

export function placedDays(state: PlanState): Map<string, number> {
  const out = new Map<string, number>();
  for (const day of state.days) {
    for (const item of day.items) out.set(item.place_id, day.day_index);
  }
  return out;
}

export function initialState(
  itinerary: Itinerary,
  shortlist: Shortlist,
  mode: TravelMode,
): PlanState {
  // Open on a day that has something on it, so a plan built on day 2 does not look like an empty
  // plan on day 1.
  const firstUsed = itinerary.days.find((d) => d.items.length > 0);
  return {
    days: itinerary.days,
    shortlist: shortlist.places,
    total: shortlist.total,
    dismissed: [],
    activeDay: firstUsed?.day_index ?? 0,
    mode,
    routes: {},
    stale: itinerary.days.filter((d) => d.items.length > 0).map((d) => d.day_index),
    unsaved: [],
    revision: 0,
    savedRevision: 0,
  };
}
