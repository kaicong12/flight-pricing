// Mirrors tp_backend/tp_api/schemas.py. Dates are YYYY-MM-DD, times HH:MM[:SS].

export type CitySuggestion = {
  place_id: string;
  description: string;
  main_text: string | null;
};

export type City = {
  city_id: string;
  name: string;
  country: string | null;
  timezone: string | null;
};

export type Ingest = {
  run_id: string;
  status: string;
};

export type TaskProgress = {
  kind: string;
  status: string;
  count: number;
};

export type Trip = {
  trip_id: string;
  city: City;
  arrive_date: string;
  arrive_time: string | null;
  depart_date: string;
  depart_time: string | null;
  extra_details: string | null;
  ingest: Ingest | null;
  notes: string[];
};

export type TripStatus = Trip & { progress: TaskProgress[] };

export type InitiatePlanRequest = {
  city_place_id: string;
  arrive_date: string;
  arrive_time: string | null;
  depart_date: string;
  depart_time: string | null;
  extra_details: string | null;
};

// FastAPI's error body: a string for HTTPException, a list for a 422.
export type ApiError = {
  detail?: string | { loc: (string | number)[]; msg: string }[];
};

export const NOTE_TEXT: Record<string, string> = {
  transit_horizon:
    "Planned beyond the transit routing horizon, walking times only — re-check nearer the date.",
};

export const TERMINAL_STATUSES = ["done", "failed", "needs_credentials"];

/** Turns any tp_api error body into one line of readable text. */
export function errorText(body: unknown, status: number): string {
  const detail = (body as ApiError | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const field = d.loc?.filter((p) => p !== "body").join(".");
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  if (status === 502) return "Could not reach the places service. Try again in a moment.";
  return `Request failed (${status}).`;
}
