"use client";

// Day tabs, which are also the drop target for moving a block to another day: only one day is on
// screen at a time, so its tab is the only place a cross-day drag can land.

import { useDroppable } from "@dnd-kit/core";

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
    <div
      role="tablist"
      aria-label="Trip days"
      className="flex flex-wrap items-center gap-1 border-b border-border px-5"
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
  const { setNodeRef, isOver } = useDroppable({
    id: `tab:${day.day_index}`,
    data: { kind: "day", day: day.day_index },
  });

  return (
    <button
      ref={setNodeRef}
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onSelect}
      className={cn(
        "-mb-px flex h-11 items-center gap-2 border-b-2 px-2.5 text-[13.5px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        active
          ? "border-ink text-ink"
          : "border-transparent text-muted-foreground hover:text-ink",
        isOver && "border-brand bg-brand-bg text-brand",
      )}
    >
      {formatDayTab(day.date)}
      {day.items.length > 0 && (
        <span className="font-mono text-[10.5px] text-faint">{day.items.length}</span>
      )}
    </button>
  );
}
