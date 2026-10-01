"use client";

// The middle column: one day, midnight to midnight, as a half-hour grid you pin places onto.
//
// Each half hour is its own droppable, so a drop reports a time rather than a pixel offset. Blocks
// are absolutely positioned from their own start_min, and overlapping ones share the width in lanes.
// A block that started on an earlier day draws its tail here too.

import { useState } from "react";

import { useDroppable } from "@dnd-kit/core";
import { PlusIcon } from "lucide-react";

import { Kbd } from "@/components/ui/kbd";
import type { CustomDraft } from "@/lib/plan-state";
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
import { useShortcut } from "@/lib/use-shortcut";
import { cn } from "@/lib/utils";

import { ActivityBlock } from "./activity-block";
import { CustomBlockDialog } from "./custom-block";

const SLOT_PX = 26;
const SLOTS = Math.round((DAY_END_MIN - DAY_START_MIN) / SLOT_MIN);

export function DayColumn({
  day,
  days,
  windowOf,
  route,
  stale,
  readOnly,
  available,
  costs,
  currency,
  onRemove,
  onReference,
  onCost,
  onResize,
  onAddCustom,
  onEditCustom,
}: {
  day: ItineraryDay;
  days: ItineraryDay[];
  windowOf: (day: number) => { from: number; to: number };
  route: DayRoute | undefined;
  stale: boolean;
  readOnly: boolean;
  /** Minutes the flight leaves usable. Outside it, a slot is shown but takes no drop. */
  available: { from: number; to: number };
  /** Each block's cost so far, already formatted, keyed the way `keyOf` keys a block. */
  costs: Map<string, string>;
  currency: string;
  onRemove: (key: string) => void;
  onReference: (key: string, url: string | null) => void;
  onCost: (item: ItineraryItem, amountCents: number | null, currency: string) => void;
  onResize: (key: string, startMin: number, durationMin: number) => void;
  onAddCustom: (startMin: number, draft: CustomDraft, durationMin: number) => void;
  onEditCustom: (key: string, draft: CustomDraft) => void;
}) {
  // Which half hour the "+" was clicked on, or the block being edited. One dialog serves both.
  const [adding, setAdding] = useState<number | null>(null);
  const [editing, setEditing] = useState<ItineraryItem | null>(null);

  const byBlock = new Map((route?.blocks ?? []).map((b) => [keyOf(b), b]));
  const perBlock = new Map<string, PlanWarning[]>();
  const dayWide: PlanWarning[] = [];
  for (const w of stale ? [] : (route?.warnings ?? [])) {
    if (w.block_id) perBlock.set(w.block_id, [...(perBlock.get(w.block_id) ?? []), w]);
    else dayWide.push(w);
  }

  const warningCount = stale ? 0 : (route?.warnings.length ?? 0);
  const pieces = piecesOn(days, day.day_index);
  const pieceOf = new Map(pieces.map((p) => [keyOf(p.item), p]));
  const placed = layout(
    pieces.map((p) => ({ ...p.item, start_min: p.from, duration_min: p.to - p.from })),
  );
  const addNext = () => setAdding(firstFree(pieces, available));
  useShortcut("b", addNext, !readOnly);

  const editingOffset = editing ? (pieceOf.get(keyOf(editing))?.offset ?? 0) : 0;
  const editingDay = day.day_index - editingOffset / DAY_END_MIN;

  return (
    <div className="px-5 pt-4 pb-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
          Day {day.day_index + 1} · {formatDayTab(day.date)}
        </h3>
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
              currency={currency}
              onRemove={() => onRemove(keyOf(p.item))}
              onReference={(url) => onReference(keyOf(p.item), url)}
              onCost={(amountCents, cur) => onCost(p.item, amountCents, cur)}
              onEdit={() => setEditing(pieceOf.get(keyOf(p.item))!.item)}
              onResize={(startMin, durationMin) =>
                onResize(keyOf(p.item), startMin, durationMin)
              }
            />
          ))}
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
          onClose={() => {
            setAdding(null);
            setEditing(null);
          }}
          onSubmit={(draft, startMin, durationMin) => {
            if (!editing) {
              if (draft) onAddCustom(startMin, draft, durationMin);
              return;
            }
            if (draft) onEditCustom(keyOf(editing), draft);
            onResize(keyOf(editing), startMin, durationMin);
          }}
        />
      )}
    </div>
  );
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
        // Tinted gaps, not transparent ones: at 5% ink on paper the hatch was easy to miss, and
        // an hour the flight has taken away has to read as unusable at a glance.
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
