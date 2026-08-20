// One trip in the list. The thumbnail is the trip's identity, because same city with different
// dates is the common case. It holds the day-1 polyline once Routes is enabled.

import Link from "next/link";

import { tripHref, type TripSummary } from "@/lib/trips";

const GRID =
  "repeating-linear-gradient(0deg, rgba(23,25,28,0.05) 0 1px, transparent 1px 34px), repeating-linear-gradient(90deg, rgba(23,25,28,0.05) 0 1px, transparent 1px 34px)";

export function TripCard({ trip }: { trip: TripSummary }) {
  return (
    <Link
      href={tripHref(trip)}
      className="block overflow-hidden rounded-xl border border-border bg-surface shadow-card transition-all hover:border-[#cdd4dd] hover:shadow-lift outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <div
        className="relative h-38 overflow-hidden bg-[#e7ebef]"
        style={{ backgroundImage: GRID }}
      >
        <span className="absolute -bottom-[22%] -left-[30%] -right-[10%] h-[78px] -rotate-6 bg-water" />
        <span className="absolute top-3 left-3 flex h-6 items-center rounded-full bg-white/90 px-2.5 font-mono text-[10.5px] tracking-[0.05em] text-ink-soft uppercase">
          {trip.thumb_label}
        </span>
        <span className="absolute right-3 bottom-3 font-mono text-[10.5px] text-ink-soft">
          {trip.thumb_note}
        </span>
      </div>

      <div className="px-4.5 pt-4 pb-4.5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-[-0.015em]">{trip.city}</h2>
          <span className="text-[12.5px] text-faint">{trip.country}</span>
        </div>
        <p className="mt-1.5 text-[13.5px] text-muted-foreground">{trip.dates}</p>
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
