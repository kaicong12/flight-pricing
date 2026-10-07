"use client";

// The middle column: one day, midnight to midnight, as a half-hour grid you pin places onto.

import { useEffect, useRef, useState } from "react";

import { useDroppable } from "@dnd-kit/core";
import { PlusIcon } from "lucide-react";

import { Kbd } from "@/components/ui/kbd";
import type { City } from "@/lib/api-types";
import { type CustomDraft, customItem } from "@/lib/plan-state";
import type { DayRoute, ItineraryDay, ItineraryItem, PlanWarning } from "@/lib/plan-types";
import {
  DAY_END_MIN,
  DAY_START_MIN,
  MIN_DURATION,
  SLOT_MIN,
  firstFree,
  formatDayTab,
  hhmm,
  keyOf,
  layout,
  piecesOn,
  warningText,
} from "@/lib/plan-types";
import { cityColor } from "@/lib/trips";
import { useShortcut } from "@/lib/use-shortcut";
import { cn } from "@/lib/utils";

import { ActivityBlock } from "./activity-block";
import { type CostEntry, CustomBlockDialog } from "./custom-block";

const SLOT_PX = 36;
const VIEW_FROM_MIN = 8 * 60;
const SLOTS = Math.round((DAY_END_MIN - DAY_START_MIN) / SLOT_MIN);

export function DayColumn({
  day,
  days,
  cities,
  onCity,
  windowOf,
  route,
  stale,
  readOnly,
  available,
  costs,
  currency,
  tags,
  onRemove,
  onReference,
  onCost,
  onResize,
  onAddCustom,
  onEditBlock,
}: {
  day: ItineraryDay;
  days: ItineraryDay[];
  cities: City[];
  onCity: (cityId: string | null) => void;
  windowOf: (day: number) => { from: number; to: number };
  route: DayRoute | undefined;
  stale: boolean;
  readOnly: boolean;
  /** Minutes the flight leaves usable. Outside it, a slot is shown but takes no drop. */
  available: { from: number; to: number };
  /** Each block's cost so far, already formatted, keyed the way `keyOf` keys a block. */
  costs: Map<string, string>;
  currency: string;
  tags: string[];
  onRemove: (key: string) => void;
  onReference: (key: string, url: string | null) => void;
  onCost: (item: ItineraryItem, cost: CostEntry) => void;
  onResize: (key: string, startMin: number, durationMin: number) => void;
  onAddCustom: (item: ItineraryItem, cost: CostEntry | null) => void;
  onEditBlock: (key: string, draft: CustomDraft) => void;
}) {
  const [adding, setAdding] = useState<number | null>(null);
  const [editing, setEditing] = useState<ItineraryItem | null>(null);
  const [preview, setPreview] = useState<{
    key: string;
    start_min: number;
    duration_min: number;
  } | null>(null);

  const byBlock = new Map((route?.blocks ?? []).map((b) => [keyOf(b), b]));
  const perBlock = new Map<string, PlanWarning[]>();
  const dayWide: PlanWarning[] = [];
  for (const w of stale ? [] : (route?.warnings ?? [])) {
    if (w.block_id) perBlock.set(w.block_id, [...(perBlock.get(w.block_id) ?? []), w]);
    else dayWide.push(w);
  }

  const warningCount = stale ? 0 : (route?.warnings.length ?? 0);
  const pieces = piecesOn(preview ? withPreview(days, preview) : days, day.day_index);
  const pieceOf = new Map(pieces.map((p) => [keyOf(p.item), p]));
  const placed = layout(
    pieces.map((p) => ({ ...p.item, start_min: p.from, duration_min: p.to - p.from })),
  );
  const addNext = () => setAdding(firstFree(pieces, available));

  const scroller = useRef<HTMLDivElement>(null);
  const viewFrom = Math.min(VIEW_FROM_MIN, ...pieces.map((p) => p.from));
  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = ((viewFrom - DAY_START_MIN) / SLOT_MIN) * SLOT_PX;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day.day_index]);
  useShortcut("b", addNext, !readOnly);

  const editingOffset = editing ? (pieceOf.get(keyOf(editing))?.offset ?? 0) : 0;
  const editingDay = day.day_index - editingOffset / DAY_END_MIN;

  return (
    <div className="px-5 pt-4 pb-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
            Day {day.day_index + 1} · {formatDayTab(day.date)}
          </h3>
          {cities.length > 1 && (
            <DayCity day={day} cities={cities} readOnly={readOnly} onCity={onCity} />
          )}
        </div>
        {!readOnly && (
          <button
            type="button"
            onClick={addNext}
            className="flex items-center gap-1.5 rounded-full text-[12.5px] font-medium text-ink-soft outline-none hover:text-ink focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <PlusIcon className="size-3.5" />
            New block
            <Kbd letter="B" />
          </button>
        )}
      </div>

      <p className="mt-1 font-mono text-[11px] text-faint">
        {[
          `${day.items.length} ${day.items.length === 1 ? "block" : "blocks"}`,
          warningCount > 0
            ? `${warningCount} ${warningCount === 1 ? "warning" : "warnings"}`
            : null,
          stale && day.items.length > 0 ? "not checked yet" : null,
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
          Drag a place from the shortlist onto the time you want it, or hover the grid for a
          {" "}
          <span className="font-medium text-ink">+</span> to add a flight or a stay.
        </p>
      )}

      <div
        ref={scroller}
        data-day-scroller
        className="mt-4 max-h-[calc(100dvh-300px)] min-h-[360px] overflow-y-auto pt-1.5"
      >
        <div className="flex" style={{ height: SLOTS * SLOT_PX }}>
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
                blocked={m < available.from || m + MIN_DURATION > available.to}
                onAdd={readOnly ? undefined : () => setAdding(m)}
              />
            ))}

            {placed.map((p) => (
              <ActivityBlock
                key={keyOf(p.item)}
                placed={p}
                piece={pieceOf.get(keyOf(p.item))!}
                block={byBlock.get(keyOf(p.item))}
                warnings={perBlock.get(keyOf(p.item)) ?? []}
                slotPx={SLOT_PX}
                readOnly={readOnly}
                cost={costs.get(keyOf(p.item)) ?? null}
                onRemove={() => onRemove(keyOf(p.item))}
                onEdit={() => setEditing(pieceOf.get(keyOf(p.item))!.item)}
                onResize={(startMin, durationMin) =>
                  onResize(keyOf(p.item), startMin, durationMin)
                }
                onPreview={(next) => setPreview(next && { key: keyOf(p.item), ...next })}
              />
            ))}
          </div>
        </div>
      </div>

      {perBlock.size > 0 && (
        <ul className="mt-3.5">
          {[...perBlock.entries()].flatMap(([blockId, ws]) =>
            ws.map((w) => (
              <li key={`${blockId}:${w.code}`} className="flex gap-2.5 py-0.5">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-alert" />
                <p className="text-[12.5px] leading-[1.45] text-alert">
                  {warningText(w, byBlock.get(blockId)?.name)}
                </p>
              </li>
            )),
          )}
        </ul>
      )}

      {(adding !== null || editing) && (
        <CustomBlockDialog
          key={editing ? keyOf(editing) : adding}
          dayIndex={editingDay}
          startMin={adding ?? DAY_START_MIN}
          days={days}
          windowOf={windowOf}
          editing={editing}
          cost={editing ? (costs.get(keyOf(editing)) ?? null) : null}
          currency={currency}
          tags={tags}
          onClose={() => {
            setAdding(null);
            setEditing(null);
          }}
          onSubmit={(draft, startMin, durationMin, { url, cost }) => {
            if (!editing) {
              onAddCustom({ ...customItem(draft, startMin, durationMin), reference_url: url }, cost);
              return;
            }
            onEditBlock(keyOf(editing), draft);
            onResize(keyOf(editing), startMin, durationMin);
            if (url !== editing.reference_url) onReference(keyOf(editing), url);
            if (cost) onCost(editing, cost);
          }}
        />
      )}
    </div>
  );
}

function withPreview(
  days: ItineraryDay[],
  { key, start_min, duration_min }: { key: string; start_min: number; duration_min: number },
): ItineraryDay[] {
  return days.map((d) => ({
    ...d,
    items: d.items.map((i) => (keyOf(i) === key ? { ...i, start_min, duration_min } : i)),
  }));
}

/** One half hour. Being a droppable is what makes a drop report a time rather than a pixel, and a
 * block sitting over a slot takes the pointer, so the hover "+" never offers a busy one. */
function Slot({
  day,
  minute,
  blocked,
  onAdd,
}: {
  day: number;
  minute: number;
  blocked: boolean;
  onAdd?: () => void;
}) {
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
        "group/slot relative border-t",
        minute % 60 === 0 ? "border-border" : "border-hairline",
        blocked && "bg-[repeating-linear-gradient(135deg,rgba(37,43,32,0.04)_0_4px,rgba(37,43,32,0.11)_4px_6px)]",
        isOver && "bg-brand-bg",
      )}
      style={{ height: SLOT_PX }}
    >
      {!blocked && onAdd && (
        <button
          type="button"
          onClick={onAdd}
          aria-label={`Add a block at ${hhmm(minute)}`}
          className="absolute inset-0 flex items-center justify-center gap-1.5 text-[11px] font-medium text-brand opacity-0 transition-opacity group-hover/slot:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <span className="grid size-4 place-items-center rounded-full border border-brand/40 bg-brand-bg">
            <PlusIcon className="size-2.5" />
          </span>
          {hhmm(minute)}
        </button>
      )}
    </div>
  );
}

function DayCity({
  day,
  cities,
  readOnly,
  onCity,
}: {
  day: ItineraryDay;
  cities: City[];
  readOnly: boolean;
  onCity: (cityId: string | null) => void;
}) {
  const color = cityColor(cities, day.city_id);
  const dot = (
    <span
      className={cn("size-2 shrink-0 rounded-full", !color && "border border-faint")}
      style={{ background: color ?? undefined }}
    />
  );
  const name = cities.find((c) => c.city_id === day.city_id)?.name;
  if (readOnly) {
    return (
      <span className="flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
        {dot}
        {name ?? "No city set"}
      </span>
    );
  }
  return (
    <label className="flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
      {dot}
      <select
        value={day.city_id ?? ""}
        onChange={(e) => onCity(e.target.value || null)}
        aria-label={`City for day ${day.day_index + 1}`}
        className="h-7 rounded-md border border-input bg-transparent px-1.5 text-[12.5px] text-ink outline-none focus-visible:border-ring"
      >
        <option value="">Pick a city</option>
        {cities.map((c) => (
          <option key={c.city_id} value={c.city_id}>
            {c.name}
          </option>
        ))}
      </select>
    </label>
  );
}
