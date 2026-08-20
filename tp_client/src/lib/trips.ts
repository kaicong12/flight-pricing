// The trips list. tp_api has no GET /trips yet, so this returns nothing until that lands.

import { getJson } from "@/lib/tp-api";

export type TripSummary = {
  trip_id: string;
  city: string;
  country: string;
  start_date: string;
  dates: string;
  status: "ingesting" | "ready";
  provisional: boolean;
  thumb_label: string;
  thumb_note: string;
  progress_text: string;
};

/** Upcoming first by start date, then past trips most-recent first. */
function byStartDate(trips: TripSummary[], today: string): TripSummary[] {
  const start = (t: TripSummary) => String(t.start_date ?? "");
  const upcoming = trips.filter((t) => start(t) >= today);
  const past = trips.filter((t) => start(t) < today);
  upcoming.sort((a, b) => start(a).localeCompare(start(b)));
  past.sort((a, b) => start(b).localeCompare(start(a)));
  return [...upcoming, ...past];
}

// The server's own calendar date. toISOString() would give the UTC date, which puts a trip
// starting today into the past bucket for part of the day.
function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export async function listTrips(): Promise<TripSummary[]> {
  const body = await getJson<unknown>("/trips");
  const trips = Array.isArray(body) ? (body as TripSummary[]).filter((t) => t?.trip_id) : [];
  return byStartDate(trips, localToday());
}

/** Status decides the destination: an ingesting trip has no itinerary to open yet. */
export function tripHref(trip: TripSummary): string {
  return trip.status === "ingesting" ? `/trips/${trip.trip_id}/building` : `/trips/${trip.trip_id}`;
}
