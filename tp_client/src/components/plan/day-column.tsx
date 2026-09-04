"use client";

// The middle column: one day as a half-hour grid you pin places onto.
//
// Each half hour is its own droppable, so a drop reports a time rather than a pixel offset. Blocks
// are absolutely positioned from their own start_min, and overlapping ones share the width in lanes.

import { useDroppable } from "@dnd-kit/core";

import type { DayRoute, ItineraryDay, PlanWarning, TravelMode } from "@/lib/plan-types";
import {
  DAY_END_MIN,
  DAY_START_MIN,
  MIN_DURATION,
  SLOT_MIN,
  formatDayTab,
  formatDistance,
  formatMinutes,
  hhmm,
  layout,
  warningText,
} from "@/lib/plan-types";
import { cn } from "@/lib/utils";

import { ActivityBlock } from "./activity-block";

const SLOT_PX = 26;
const SLOTS = Math.round((DAY_END_MIN - DAY_START_MIN) / SLOT_MIN);

export function DayColumn({
  day,
  route,
  mode,
  stale,
  available,
  onRemove,
  onResize,
}: {
  day: ItineraryDay;
  route: DayRoute | undefined;
  mode: TravelMode;
  stale: boolean;
  /** Minutes the flight leaves usable. Outside it, a slot is shown but takes no drop. */
  available: { from: number; to: number };
  onRemove: (placeId: string) => void;
  onResize: (placeId: string, startMin: number, durationMin: number) => void;
}) {
  const routed = Boolean(route?.routed) && !stale;
  const byPlace = new Map((route?.blocks ?? []).map((b) => [b.place_id, b]));
  const perPlace = new Map<string, PlanWarning[]>();
  const dayWide: PlanWarning[] = [];
  for (const w of stale ? [] : (route?.warnings ?? [])) {
    if (w.place_id) perPlace.set(w.place_id, [...(perPlace.get(w.place_id) ?? []), w]);
    else dayWide.push(w);
  }

  const warningCount = stale ? 0 : (route?.warnings.length ?? 0);
  const placed = layout(day.items);

  return (
    <div className="px-5 pt-4 pb-5">
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

      {day.items.length === 0 && (
        <p className="mt-3.5 text-[13px] text-muted-foreground">
          Drag a place from the shortlist onto the time you want it.
        </p>
      )}

      <div className="mt-4 flex" style={{ height: SLOTS * SLOT_PX }}>
        <div className="relative w-11 shrink-0">
          {Array.from({ length: SLOTS }, (_, i) => DAY_START_MIN + i * SLOT_MIN)
            .filter((m) => m % 60 === 0)
            .map((m) => (
              <span
                key={m}
                className="absolute font-mono text-[10.5px] text-faint"
                style={{ top: ((m - DAY_START_MIN) / SLOT_MIN) * SLOT_PX - 6 }}
              >
                {hhmm(m)}
              </span>
            ))}
        </div>

        <div data-grid className="relative flex-1">
          {Array.from({ length: SLOTS }, (_, i) => DAY_START_MIN + i * SLOT_MIN).map((m) => (
            <Slot
              key={m}
              day={day.day_index}
              minute={m}
              // A slot has to fit the shortest block there is, or dropping on it cannot work.
              blocked={m < available.from || m + MIN_DURATION > available.to}
            />
          ))}

          {placed.map((p) => (
            <ActivityBlock
              key={p.item.place_id}
              placed={p}
              block={byPlace.get(p.item.place_id)}
              warnings={perPlace.get(p.item.place_id) ?? []}
              slotPx={SLOT_PX}
              onRemove={() => onRemove(p.item.place_id)}
              onResize={(startMin, durationMin) =>
                onResize(p.item.place_id, startMin, durationMin)
              }
            />
          ))}
        </div>
      </div>

      {perPlace.size > 0 && (
        <ul className="mt-3.5">
          {[...perPlace.entries()].flatMap(([placeId, ws]) =>
            ws.map((w) => (
              <li key={`${placeId}:${w.code}`} className="flex gap-2.5 py-0.5">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-alert" />
                <p className="text-[12.5px] leading-[1.45] text-alert">{warningText(w)}</p>
              </li>
            )),
          )}
        </ul>
      )}
    </div>
  );
}

/** One half hour. Being a droppable is what makes a drop report a time rather than a pixel. */
function Slot({ day, minute, blocked }: { day: number; minute: number; blocked: boolean }) {
  const { setNodeRef, isOver } = useDroppable({
    id: `slot:${day}:${minute}`,
    data: { kind: "slot", day, minute },
    disabled: blocked,
  });

  return (
    <div
      ref={setNodeRef}
      aria-hidden={blocked}
      className={cn(
        "border-t",
        minute % 60 === 0 ? "border-border" : "border-hairline",
        blocked && "bg-[repeating-linear-gradient(135deg,transparent_0_5px,rgba(37,43,32,0.05)_5px_6px)]",
        isOver && "bg-brand-bg",
      )}
      style={{ height: SLOT_PX }}
    />
  );
}

