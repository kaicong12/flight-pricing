// Mirrors tp_api/plan_schemas.py by hand — there is no codegen step. Warnings arrive as codes; the
// English for them lives here.

export type TravelMode = "walk" | "transit";

export type ShortlistPlace = {
  place_id: string;
  name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  rating: number | null;
  rating_count: number | null;
  primary_type: string | null;
  category: string | null;
  why_go: string | null;
  sources: string[];
  mention_count: number;
  in_itinerary: boolean;
  day_index: number | null;
  default_duration_min: number;
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
  position: number;
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
  start_time: string;
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
      return `Arrive ${d.arrive}, but it opens ${d.opens} — ${d.wait_min} min waiting around.`;
    case "closes_before_done":
      return `Arrive ${d.arrive}, need ${d.need_min} min, closes ${d.closes}. Move it earlier.`;
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

/** "14:20" from tp_api's "14:20:00". */
export function shortTime(t: string | null): string | null {
  return t ? t.slice(0, 5) : null;
}
