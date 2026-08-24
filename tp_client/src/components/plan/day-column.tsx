"use client";

// The middle column: one day as ordered blocks with the travel between them.

import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";

import type { DayRoute, ItineraryDay, PlanWarning, TravelMode } from "@/lib/plan-types";
import { formatDayTab, formatDistance, formatMinutes, warningText } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

import { ActivityBlock } from "./activity-block";
import { LegRow } from "./leg-row";

export function DayColumn({
  day,
  route,
  mode,
  stale,
  onRemove,
  onDuration,
}: {
  day: ItineraryDay;
  route: DayRoute | undefined;
  mode: TravelMode;
  stale: boolean;
  onRemove: (placeId: string) => void;
  onDuration: (placeId: string, minutes: number) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `day:${day.day_index}`,
    data: { kind: "day", day: day.day_index },
  });

  const routed = Boolean(route?.routed) && !stale;
  const byPlace = new Map((route?.blocks ?? []).map((b) => [b.place_id, b]));
  const perPlace = new Map<string, PlanWarning[]>();
  const dayWide: PlanWarning[] = [];
  for (const w of stale ? [] : (route?.warnings ?? [])) {
    if (w.place_id) perPlace.set(w.place_id, [...(perPlace.get(w.place_id) ?? []), w]);
    else dayWide.push(w);
  }

  const warningCount = stale ? 0 : (route?.warnings.length ?? 0);

  return (
    <div ref={setNodeRef} className="min-h-[420px] px-5 pt-4 pb-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
          Day {day.day_index + 1} · {formatDayTab(day.date)}
        </h3>
        <span className="font-mono text-[10.5px] tracking-[0.05em] text-faint uppercase">
          {mode}
        </span>
      </div>

      <p className="mt-1 font-mono text-[11px] text-faint">
        {[
          `${day.items.length} ${day.items.length === 1 ? "block" : "blocks"}`,
          routed && route ? `${formatDistance(route.total_distance_m)} ${mode}ing` : null,
          routed && route ? formatMinutes(route.total_travel_s) : null,
          routed && warningCount > 0
            ? `${warningCount} ${warningCount === 1 ? "warning" : "warnings"}`
            : null,
          stale && day.items.length > 1 ? "not routed yet" : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>

      {dayWide.map((w) => (
        <div
          key={w.code}
          className="mt-3.5 flex items-start gap-2.5 rounded-[13px] border border-warn-border bg-warn-bg px-3.5 py-2.5"
        >
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warn" />
          <p className="text-[12.5px] leading-[1.45] text-warn">{warningText(w)}</p>
        </div>
      ))}

      <SortableContext
        items={day.items.map((i) => `item:${i.place_id}`)}
        strategy={verticalListSortingStrategy}
      >
        <ol className="mt-4">
          {day.items.map((item, index) => (
            <li key={item.place_id}>
              <ActivityBlock
                item={item}
                block={byPlace.get(item.place_id)}
                warnings={perPlace.get(item.place_id) ?? []}
                index={index}
                onRemove={() => onRemove(item.place_id)}
                onDuration={(minutes) => onDuration(item.place_id, minutes)}
              />
              {index < day.items.length - 1 && (
                <LegRow leg={route?.legs[index]} mode={mode} routed={routed} />
              )}
            </li>
          ))}
        </ol>
      </SortableContext>

      <div
        className={cn(
          "mt-4 grid h-16 place-items-center rounded-card-sm border border-dashed text-[13px] transition-colors",
          isOver ? "border-brand bg-brand-bg text-brand" : "border-[#d7cfba] text-faint",
        )}
      >
        {day.items.length === 0
          ? "Drag a place from the shortlist to start this day"
          : "Drag a place from the shortlist to add it here"}
      </div>
    </div>
  );
}
