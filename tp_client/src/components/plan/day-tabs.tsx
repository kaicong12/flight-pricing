"use client";

// Day tabs; not drop targets.

import { useEffect, useRef } from "react";

import type { City } from "@/lib/api-types";
import type { ItineraryDay } from "@/lib/plan-types";
import { formatDayTab } from "@/lib/plan-types";
import { cityColor } from "@/lib/trips";
import { cn } from "@/lib/utils";

export function DayTabs({
  days,
  cities,
  activeDay,
  onSelect,
}: {
  days: ItineraryDay[];
  cities: City[];
  activeDay: number;
  onSelect: (day: number) => void;
}) {
  return (
    // overflow-y hidden: a scrolling box turns the tabs' -mb-px into vertical overflow.
    <div
      role="tablist"
      aria-label="Trip days"
      className="flex items-center gap-1 overflow-x-auto overflow-y-hidden border-b border-border px-5"
    >
      {days.map((day) => (
        <DayTab
          key={day.day_index}
          day={day}
          city={
            cities.length > 1 ? (cities.find((c) => c.city_id === day.city_id) ?? null) : undefined
          }
          color={cityColor(cities, day.city_id)}
          active={day.day_index === activeDay}
          onSelect={() => onSelect(day.day_index)}
        />
      ))}
    </div>
  );
}

function DayTab({
  day,
  city,
  color,
  active,
  onSelect,
}: {
  day: ItineraryDay;
  /** Null is a day not yet put in a city; undefined is a one-city trip, where every day is. */
  city: City | null | undefined;
  color: string | null;
  active: boolean;
  onSelect: () => void;
}) {
  const node = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (active) node.current?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [active]);

  return (
    <button
      ref={node}
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onSelect}
      className={cn(
        "-mb-px flex shrink-0 flex-col justify-center whitespace-nowrap border-b-2 px-2.5 text-[13.5px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        city === undefined ? "h-11" : "h-13",
        active
          ? "border-ink text-ink"
          : "border-transparent text-muted-foreground hover:text-ink",
      )}
    >
      <span className="flex items-center gap-2">
        {formatDayTab(day.date)}
        {day.items.length > 0 && (
          <span className="font-mono text-[10.5px] text-faint">{day.items.length}</span>
        )}
      </span>
      {city !== undefined && (
        <span className="flex items-center gap-1 text-[11px] font-normal text-muted-foreground">
          <span
            className={cn("size-1.5 rounded-full", !color && "border border-faint")}
            style={{ background: color ?? undefined }}
          />
          {city?.name ?? "No city"}
        </span>
      )}
    </button>
  );
}
