// The trips list: tp_api's GET /trips shaped for the card, which wants display strings.

import { getJson } from "@/lib/tp-api";
import { TERMINAL_STATUSES, type City, type Trip } from "@/lib/api-types";

export type TripListItem = Pick<Trip, "trip_id" | "name" | "city" | "arrive_date" | "depart_date" | "ingest" | "notes"> & {
  tasks_done: number;
  tasks_total: number;
  place_count: number;
};

export type TripSummary = {
  trip_id: string;
  name: string | null;
  title: string;
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

/** The city name is the fallback, so an unnamed trip still reads as something. */
export function tripTitle(trip: { name?: string | null; city?: City | null }): string {
  return trip.name?.trim() || trip.city?.name || "Untitled trip";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(iso: string): { d: number; m: number; y: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  return m ? { y: Number(m[1]), m: Number(m[2]) - 1, d: Number(m[3]) } : null;
}

/** "12–15 Mar 2026", widening to month and year only when the range crosses one. */
export function formatRange(arrive: string, depart: string): string {
  const a = parts(arrive);
  const b = parts(depart);
  if (!a || !b) return "";
  if (a.y !== b.y) return `${a.d} ${MONTHS[a.m]} ${a.y} – ${b.d} ${MONTHS[b.m]} ${b.y}`;
  if (a.m !== b.m) return `${a.d} ${MONTHS[a.m]} – ${b.d} ${MONTHS[b.m]} ${a.y}`;
  if (a.d === b.d) return `${a.d} ${MONTHS[a.m]} ${a.y}`;
  return `${a.d}–${b.d} ${MONTHS[a.m]} ${a.y}`;
}

export function nightCount(arrive: string, depart: string): number {
  const a = Date.parse(`${arrive}T00:00:00`);
  const b = Date.parse(`${depart}T00:00:00`);
  return Number.isNaN(a) || Number.isNaN(b) ? 0 : Math.max(0, Math.round((b - a) / 86_400_000));
}

function summarise(item: TripListItem): TripSummary {
  const status = item.ingest && !TERMINAL_STATUSES.includes(item.ingest.status) ? "ingesting" : "ready";
  const nights = nightCount(item.arrive_date, item.depart_date);
  return {
    trip_id: item.trip_id,
    name: item.name ?? null,
    title: tripTitle(item),
    city: item.city?.name ?? "",
    country: item.city?.country ?? "",
    start_date: item.arrive_date,
    dates: formatRange(item.arrive_date, item.depart_date),
    status,
    provisional: (item.notes ?? []).includes("transit_horizon"),
    thumb_label: item.city?.name ?? "",
    thumb_note: nights === 1 ? "1 night" : `${nights} nights`,
    progress_text: progressText(item, status),
  };
}

function progressText(item: TripListItem, status: TripSummary["status"]): string {
  if (status === "ingesting") {
    return item.tasks_total > 0
      ? `Reading sources · ${item.tasks_done}/${item.tasks_total}`
      : "Starting up";
  }
  if (item.ingest?.status === "failed") return "Ingestion failed";
  if (item.ingest?.status === "needs_credentials") return "Needs credentials";
  if (item.place_count > 0) return `${item.place_count} places found`;
  return "Ready";
}

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
  const items = Array.isArray(body) ? (body as TripListItem[]).filter((t) => t?.trip_id) : [];
  return byStartDate(items.map(summarise), localToday());
}

export function tripHref(trip: { trip_id: string }): string {
  return `/trip/${trip.trip_id}`;
}
