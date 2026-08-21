// The landing screen once a trip exists.

import Link from "next/link";

import { AppHeader } from "@/components/app-header";
import { TripCard } from "@/components/trip-card";
import { listTrips } from "@/lib/trips";

export const metadata = { title: "Trips" };
export const dynamic = "force-dynamic";

export default async function TripsPage() {
  const trips = await listTrips();
  const ingesting = trips.filter((t) => t.status === "ingesting").length;

  return (
    <div className="min-h-dvh bg-page pb-24">
      <AppHeader />
      {trips.length === 0 ? <Empty /> : <List trips={trips} ingesting={ingesting} />}
    </div>
  );
}

function List({ trips, ingesting }: { trips: Awaited<ReturnType<typeof listTrips>>; ingesting: number }) {
  return (
    <main className="mx-auto max-w-[1180px] px-7 pt-11">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-[-0.015em]">Trips</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {trips.length} {trips.length === 1 ? "trip" : "trips"}.
            {ingesting > 0 && ` ${ingesting === 1 ? "One is" : `${ingesting} are`} still reading videos.`}
          </p>
        </div>
        <Link
          href="/"
          className="flex h-10 shrink-0 items-center rounded-full bg-ink px-4 text-[13.5px] font-medium whitespace-nowrap text-primary-foreground transition-colors hover:bg-ink-hover outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          Plan a city trip
        </Link>
      </div>

      <div className="mt-7 grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(min(340px,100%),1fr))]">
        {trips.map((trip) => (
          <TripCard key={trip.trip_id} trip={trip} />
        ))}
      </div>
    </main>
  );
}

function Empty() {
  return (
    <main className="mx-auto max-w-[620px] px-7 pt-30 text-center">
      <div className="mx-auto grid size-14 place-items-center rounded-[58%_42%_46%_54%_/_52%_56%_44%_48%] border border-border surface">
        <span className="size-5 rounded-[999px_6px_999px_6px] bg-linear-135 from-[#b9c4ab] to-[#cfc6ae]" />
      </div>
      <h1 className="mt-6 text-[26px] font-semibold tracking-[-0.015em]">No trips yet</h1>
      <p className="mt-2.5 text-[14.5px] leading-[1.55] text-muted-foreground">
        Pick a city and your dates. We read real travel videos and posts to find places worth going
        to, then you decide the order.
      </p>
      <Link
        href="/"
        className="mt-6.5 inline-flex h-10.5 items-center rounded-full bg-ink px-5 text-[13.5px] font-medium text-primary-foreground transition-colors hover:bg-ink-hover outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        Plan a city trip
      </Link>
    </main>
  );
}
