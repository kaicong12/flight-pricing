"use client";

// Title, the whole-plan caveats, and the two actions. "Provisional" is a property of how far out the
// date is, not of the ordering, so it never clears by editing the plan.

import { Check, Link2, RefreshCw } from "lucide-react";
import { useState } from "react";

import { TripName } from "@/components/trip-name";
import type { Trip } from "@/lib/api-types";
import type { TravelMode } from "@/lib/plan-types";
import { PROVISIONAL_TEXT, shortTime } from "@/lib/plan-types";
import { formatRange } from "@/lib/trips";
import { cn } from "@/lib/utils";

export function PlanHeader({
  trip,
  placeCount,
  provisional,
  mode,
  stale,
  routing,
  onMode,
  onReroute,
}: {
  trip: Trip;
  placeCount: number;
  provisional: string[];
  mode: TravelMode;
  stale: boolean;
  routing: boolean;
  onMode: (mode: TravelMode) => void;
  onReroute: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const arrive = shortTime(trip.arrive_time);
  const depart = shortTime(trip.depart_time);

  async function share() {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div>
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="min-w-0 text-3xl font-semibold tracking-[-0.015em]">
            <TripName
              tripId={trip.trip_id}
              name={trip.name}
              fallback={trip.city.name}
              className="text-3xl font-semibold tracking-[-0.015em]"
            />
          </h1>
          {provisional.length > 0 && (
            <span className="flex h-6.5 items-center rounded-full bg-warn-bg px-2.5 text-xs font-medium text-warn">
              Provisional · {provisional.map((p) => PROVISIONAL_TEXT[p] ?? p).join(" · ")}
            </span>
          )}
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          {[
            trip.name?.trim() ? trip.city.name : null,
            formatRange(trip.arrive_date, trip.depart_date),
            arrive && `lands ${arrive}`,
            depart && `leaves ${depart}`,
            `${placeCount} places found`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex h-9 items-center rounded-full bg-page p-0.5">
          {(["walk", "transit"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => onMode(m)}
              aria-pressed={mode === m}
              className={cn(
                "flex h-8 items-center rounded-full px-3 text-[13px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                mode === m ? "bg-surface text-ink shadow-card" : "text-muted-foreground hover:text-ink",
              )}
            >
              {m === "walk" ? "Walk" : "Transit"}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={share}
          className="flex h-9 items-center gap-1.5 rounded-full border border-border bg-surface px-3.5 text-[13px] font-medium text-ink transition-colors hover:border-[#c6bda4] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {copied ? <Check className="size-3.5 text-ok" /> : <Link2 className="size-3.5" />}
          {copied ? "Copied" : "Share"}
        </button>

        <button
          type="button"
          onClick={onReroute}
          disabled={routing}
          className={cn(
            "flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            "bg-ink text-primary-foreground hover:bg-ink-hover disabled:opacity-60",
            stale && !routing && "ring-2 ring-brand/40",
          )}
        >
          <RefreshCw
            className={cn(
              "size-3.5",
              routing && "animate-[tp-spin_0.9s_linear_infinite] motion-reduce:animate-none",
            )}
          />
          {routing ? "Routing…" : "Re-route day"}
        </button>
      </div>
    </div>
  );
}
