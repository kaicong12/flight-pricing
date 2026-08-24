// The planning screen: shortlist beside the ordered day beside the map. The user owns the order; we
// route it and say what does not work.

import Link from "next/link";
import { notFound } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { PlanBoard } from "@/components/plan/plan-board";
import type { TripStatus } from "@/lib/api-types";
import type { Itinerary, Shortlist } from "@/lib/plan-types";
import { getJson } from "@/lib/tp-api";

export const dynamic = "force-dynamic";

const EMPTY_SHORTLIST: Shortlist = { total: 0, shown: 0, places: [] };

export async function generateMetadata({ params }: PageProps<"/trip/[tripId]/plan">) {
  const { tripId } = await params;
  const trip = await getJson<TripStatus>(`/trips/${encodeURIComponent(tripId)}`);
  return { title: trip ? `${trip.city.name} plan` : "Plan" };
}

export default async function PlanPage({ params }: PageProps<"/trip/[tripId]/plan">) {
  const { tripId } = await params;
  const id = encodeURIComponent(tripId);

  const [trip, itinerary, shortlist] = await Promise.all([
    getJson<TripStatus>(`/trips/${id}`),
    getJson<Itinerary>(`/trips/${id}/itinerary`),
    getJson<Shortlist>(`/trips/${id}/shortlist?limit=40`),
  ]);
  if (!trip || !itinerary) notFound();

  // CityOut carries no coordinates, so the map opens on the places themselves. Every resolved place
  // has a lat/lon, and a city with none has nothing to show anyway.
  const center = firstPoint(itinerary, shortlist);

  return (
    <div className="min-h-dvh bg-page pb-16">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1560px] px-7 pt-9">
        <Link
          href={`/trip/${id}`}
          className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase transition-colors hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          ← Trip status
        </Link>

        <div className="mt-4">
          <PlanBoard
            trip={trip}
            center={center}
            initialItinerary={itinerary}
            initialShortlist={shortlist ?? EMPTY_SHORTLIST}
          />
        </div>
      </main>
    </div>
  );
}

function firstPoint(
  itinerary: Itinerary,
  shortlist: Shortlist | null,
): { lat: number; lon: number } | null {
  const candidates = [
    ...itinerary.days.flatMap((d) => d.items),
    ...(shortlist?.places ?? []),
  ];
  for (const c of candidates) {
    if (c.lat !== null && c.lon !== null) return { lat: c.lat, lon: c.lon };
  }
  return null;
}
