// One trip: its dates and the live ingestion checklist. The shortlist lands here once tp_api
// exposes places.

import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { DeleteTrip } from "@/components/delete-trip";
import { TripProgress } from "@/components/trip-progress";
import { type TripStatus } from "@/lib/api-types";
import { currentUser } from "@/lib/session";
import { getJson } from "@/lib/tp-api";
import { cityNames, formatRange, nightCount } from "@/lib/trips";

export const dynamic = "force-dynamic";

async function loadTrip(tripId: string): Promise<TripStatus | null> {
  return getJson<TripStatus>(`/trips/${encodeURIComponent(tripId)}`);
}

export async function generateMetadata({ params }: PageProps<"/trip/[tripId]">) {
  const { tripId } = await params;
  const trip = await loadTrip(tripId);
  return { title: trip ? `${cityNames(trip)} trip` : "Trip" };
}

export default async function TripPage({ params }: PageProps<"/trip/[tripId]">) {
  const { tripId } = await params;
  // Signed out is not the same as no access, and a shared link is the common way to arrive here
  // without a session. currentUser is memoized, so the header below re-uses this call.
  const user = await currentUser();
  if (!user) redirect("/login");

  const trip = await loadTrip(tripId);
  if (!trip) notFound();

  const nights = nightCount(trip.arrive_date, trip.depart_date);
  const countries = [
    ...new Set((trip.cities.length ? trip.cities : [trip.city]).map((c) => c.country).filter(Boolean)),
  ].join(" · ");

  return (
    <div className="min-h-dvh bg-page pb-24">
      <AppHeader user={user} />
      <main className="mx-auto w-full max-w-[820px] px-7 pt-11">
        <Link
          href="/trips"
          className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase transition-colors hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          ← All trips
        </Link>

        <div className="mt-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div>
            <h1 className="text-3xl font-semibold tracking-[-0.015em]">{cityNames(trip)}</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {formatRange(trip.arrive_date, trip.depart_date)} · {nights === 1 ? "1 night" : `${nights} nights`}
            </p>
          </div>
          {countries && <span className="font-mono text-[11.5px] text-faint">{countries}</span>}
        </div>

        {trip.deleted && (
          <div className="mt-5 flex items-center gap-3.5 rounded-[13px] border border-alert/25 bg-alert-bg px-4 py-3.5">
            <span className="size-1.5 shrink-0 rounded-full bg-alert" />
            <p className="text-[13px] leading-[1.5] text-alert">
              Deleted. It no longer shows in your trips list.
            </p>
          </div>
        )}

        {trip.extra_details && (
          <p className="mt-5 border-l-2 border-border pl-4 text-[13.5px] leading-[1.55] text-ink-soft">
            {trip.extra_details}
          </p>
        )}

        <TripProgress initial={trip} />

        <div className="mt-4 flex items-center justify-between gap-4">
          <p className="font-mono text-[11px] text-faint">trip_id: {trip.trip_id}</p>
          {!trip.deleted && <DeleteTrip tripId={trip.trip_id} city={trip.city.name} />}
        </div>
      </main>
    </div>
  );
}
