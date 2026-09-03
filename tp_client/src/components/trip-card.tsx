// One trip in the list. The thumbnail is the trip's identity, because same city with different
// dates is the common case. It holds the day-1 polyline once Routes is enabled.

import Link from "next/link";

import { TripName } from "@/components/trip-name";
import { tripHref, type TripSummary } from "@/lib/trips";

const CONTOURS =
  "repeating-radial-gradient(circle at 28% 118%, rgba(58,74,53,0.09) 0 1.5px, transparent 1.5px 20px)";

export function TripCard({ trip }: { trip: TripSummary }) {
  return (
    <Link
      href={tripHref(trip)}
      className="block overflow-hidden rounded-card border border-border surface shadow-card transition-all hover:border-[#c6bda4] hover:shadow-lift outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <div
        className="relative h-38 overflow-hidden bg-land"
        style={{ backgroundImage: CONTOURS }}
      >
        <span className="water absolute -bottom-[22%] -left-[30%] -right-[10%] h-[82px] -rotate-6 rounded-[46%_54%_38%_62%_/_60%_40%_56%_44%]" />
        <span className="absolute top-3 left-3 flex h-6 items-center rounded-full bg-white/92 px-2.5 font-mono text-[10.5px] tracking-[0.04em] text-ink-soft uppercase">
          {trip.thumb_label}
        </span>
        <span className="absolute right-3 bottom-3 flex h-[22px] items-center rounded-full bg-surface/90 px-2.5 font-mono text-[10.5px] text-ink-soft">
          {trip.thumb_note}
        </span>
      </div>

      <div className="px-4.5 pt-4 pb-4.5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="min-w-0 text-lg font-semibold tracking-[-0.015em]">
            <TripName
              tripId={trip.trip_id}
              name={trip.name}
              fallback={trip.city}
              className="text-lg font-semibold tracking-[-0.015em]"
            />
          </h2>
          <span className="shrink-0 text-[12.5px] text-faint">{trip.country}</span>
        </div>
        <p className="mt-1.5 text-[13.5px] text-muted-foreground">
          {trip.name?.trim() ? `${trip.city} · ${trip.dates}` : trip.dates}
        </p>
        <div className="mt-3.5 flex items-center gap-2">
          {trip.status === "ingesting" ? (
            <span className="inline-flex h-6 items-center gap-[7px] rounded-full bg-brand-bg px-2.5 text-xs font-medium text-brand">
              <span className="size-1.5 animate-[tp-pulse_1.4s_ease-in-out_infinite] motion-reduce:animate-none rounded-full bg-brand" />
              {trip.progress_text}
            </span>
          ) : (
            <span className="inline-flex h-6 items-center rounded-full bg-ok-bg px-2.5 text-xs font-medium text-ok">
              {trip.progress_text}
            </span>
          )}
          {trip.provisional && (
            <span className="inline-flex h-6 items-center rounded-full bg-warn-bg px-2.5 text-xs font-medium text-warn">
              Provisional
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
