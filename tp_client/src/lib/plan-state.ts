// All of the planning screen's mutable state, as one pure reducer.
//
// A reducer rather than a dozen useStates because the transitions are interdependent: pinning a place
// to another day changes two days, re-sorts both, marks both unsaved and both un-routed. Doing that
// in one place is what stops a half-applied drag.

import { DEFAULT_DURATION } from "@/lib/plan-types";
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
  /** Edited since it was last routed, so the legs no longer describe it. */
  stale: number[];
  /** Which days the next write must send. */
  unsaved: number[];
  /** Bumped by every edit. A write carries the revision it saw, so a response that a newer edit has
   *  already superseded can be discarded instead of clobbering it. */
  revision: number;
  savedRevision: number;
};

export type PlanAction =
  | { type: "add"; place: ShortlistPlace; day: number; startMin: number; durationMin: number }
  | { type: "remove"; day: number; placeId: string }
  | { type: "pin"; placeId: string; fromDay: number; toDay: number; startMin: number }
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

/** The day's sequence, matching how the server reads it back — legs are indexed against this. */
function inTimeOrder(items: ItineraryItem[]): ItineraryItem[] {
  return [...items].sort(
    (a, b) => a.start_min - b.start_min || a.place_id.localeCompare(b.place_id),
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
    place_id: place.place_id,
    name: place.name,
    lat: place.lat,
    lon: place.lon,
    start_min: startMin,
    duration_min: durationMin,
    category: place.category,
    primary_type: place.primary_type,
  };
}

export function planReducer(state: PlanState, action: PlanAction): PlanState {
  switch (action.type) {
    case "add": {
      // A place sits on at most one day, so dropping one already placed just re-pins it.
      const current = dayOf(state, action.place.place_id);
      if (current !== null) {
        return planReducer(state, {
          type: "pin",
          placeId: action.place.place_id,
          fromDay: current,
          toDay: action.day,
          startMin: action.startMin,
        });
      }
      const items = [
        ...itemsOf(state, action.day),
        itemFor(action.place, action.startMin, action.durationMin),
      ];
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    case "remove": {
      const items = itemsOf(state, action.day).filter((i) => i.place_id !== action.placeId);
      return { ...state, days: setDay(state, action.day, items), ...touched(state, [action.day]) };
    }

    // One action for both "move it to 14:00" and "move it to tomorrow at 14:00": a drop always
    // names a day and a time, and there is no ordering left to state separately.
    case "pin": {
      const moving = itemsOf(state, action.fromDay).find((i) => i.place_id === action.placeId);
      if (!moving) return state;
      const pinned = { ...moving, start_min: action.startMin };

      if (action.fromDay === action.toDay) {
        // A drop that changes nothing must not bump the revision, or it re-routes for free.
        if (moving.start_min === action.startMin) return state;
        const items = itemsOf(state, action.toDay).map((i) =>
          i.place_id === action.placeId ? pinned : i,
        );
        return {
          ...state,
          days: setDay(state, action.toDay, items),
          ...touched(state, [action.toDay]),
        };
      }

      const source = itemsOf(state, action.fromDay).filter((i) => i.place_id !== action.placeId);
      const target = [...itemsOf(state, action.toDay), pinned];
      const days = state.days.map((d) => {
        if (d.day_index === action.fromDay) return { ...d, items: inTimeOrder(source) };
        if (d.day_index === action.toDay) return { ...d, items: inTimeOrder(target) };
        return d;
      });
      return { ...state, days, ...touched(state, [action.fromDay, action.toDay]) };
    }

    case "duration": {
      const current = itemsOf(state, action.day).find((i) => i.place_id === action.placeId);
      if (!current || current.duration_min === action.minutes) return state;
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
