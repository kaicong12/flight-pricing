"use client";

// Day tabs. Deliberately not drop targets: a block belongs to the day it is on, and dragging it
// only moves it in time. Moving one to another day is remove-then-add-back, so switching tabs
// mid-drag cannot silently reschedule it.

import { useEffect, useRef } from "react";

import type { ItineraryDay } from "@/lib/plan-types";
import { formatDayTab } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

export function DayTabs({
  days,
  activeDay,
  onSelect,
}: {
  days: ItineraryDay[];
  activeDay: number;
  onSelect: (day: number) => void;
}) {
  return (
    // One row that scrolls: a fortnight wrapped onto three rows pushed the day itself off screen.
    // overflow-y stays hidden because a scrolling box turns the tabs' -mb-px into vertical overflow.
    <div
      role="tablist"
      aria-label="Trip days"
      className="flex items-center gap-1 overflow-x-auto overflow-y-hidden border-b border-border px-5"
    >
      {days.map((day) => (
        <DayTab
          key={day.day_index}
          day={day}
          active={day.day_index === activeDay}
          onSelect={() => onSelect(day.day_index)}
        />
      ))}
    </div>
  );
}

function DayTab({
  day,
  active,
  onSelect,
}: {
  day: ItineraryDay;
  active: boolean;
  onSelect: () => void;
}) {
  const node = useRef<HTMLButtonElement | null>(null);

  // Landing on a trip whose active day is far along would otherwise leave the selected tab outside
  // the scrolled row.
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
        "-mb-px flex h-11 shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-2.5 text-[13.5px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        active
          ? "border-ink text-ink"
          : "border-transparent text-muted-foreground hover:text-ink",
      )}
    >
      {formatDayTab(day.date)}
      {day.items.length > 0 && (
        <span className="font-mono text-[10.5px] text-faint">{day.items.length}</span>
      )}
    </button>
  );
}
