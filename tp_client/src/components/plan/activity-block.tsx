"use client";

// One activity block, positioned on the grid at the time the user pinned it to. Drag the body to
// move it earlier or later within its own day, drag either edge to change how long you spend there.
// Use the X to take it off the day; there is no drag that moves it to another one. A block that
// runs into later days moves from its first day and resizes from its last; the pencil does the rest.
//
// Warnings sit under the grid rather than inside the block: a block's height is its duration, so
// there is no room to grow into, and the alert border already says which block is the problem.

import { useDraggable } from "@dnd-kit/core";
import { Link2, Pencil, X } from "lucide-react";

import type { Piece, PlacedItem, PlanBlock, PlanWarning } from "@/lib/plan-types";
import {
  DAY_END_MIN,
  DAY_START_MIN,
  MIN_DURATION,
  SLOT_MIN,
  endOf,
  hhmm,
  keyOf,
  resize,
  slotAt,
} from "@/lib/plan-types";
import { cn } from "@/lib/utils";

// A block of a few minutes still needs room to be seen and grabbed.
const MIN_HEIGHT_PX = 12;

export function ActivityBlock({
  placed,
  piece,
  block,
  warnings,
  slotPx,
  readOnly,
  cost,
  onRemove,
  onResize,
  onEdit,
}: {
  /** Positioned by this day's share of the block, which `piece` describes. */
  placed: PlacedItem;
  piece: Piece;
  block: PlanBlock | undefined;
  warnings: PlanWarning[];
  slotPx: number;
  readOnly: boolean;
  /** What this block has cost so far, already formatted — a block can carry more than one cost. */
  cost: string | null;
  onRemove: () => void;
  onResize: (startMin: number, durationMin: number) => void;
  onEdit: () => void;
}) {
  const { lane, lanes } = placed;
  const { item, offset } = piece;
  const continued = offset > 0;
  const endsHere = endOf(item) - offset <= DAY_END_MIN;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `item:${keyOf(item)}`,
    data: { kind: "item", item },
    disabled: readOnly || continued,
  });
  const own = item.kind === "custom";

  const broken = warnings.length > 0;
  // At 30 minutes or less there is only room for one line, so the times move to the title.
  const short = placed.item.duration_min <= MIN_DURATION;
  const extraDays = Math.ceil(endOf(item) / DAY_END_MIN) - 1;
  const until = `${hhmm(endOf(item))}${extraDays > 0 ? ` +${extraDays}d` : ""}`;

  /**
   * Raw pointer events rather than dnd-kit, committed once on pointerup: the board re-routes on
   * every duration change, so dispatching per pixel would re-check the day per pixel.
   */
  const startResize = (edge: "top" | "bottom") => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const grid = (e.currentTarget as HTMLElement).closest("[data-grid]")?.getBoundingClientRect();
    if (!grid) return;

    let next = { start_min: item.start_min, duration_min: item.duration_min };
    const move = (ev: PointerEvent) => {
      next = resize(item, edge, slotAt(ev.clientY - grid.top, slotPx), offset);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (next.start_min !== item.start_min || next.duration_min !== item.duration_min) {
        onResize(next.start_min, next.duration_min);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div
      className="absolute"
      style={{
        top: ((placed.item.start_min - DAY_START_MIN) / SLOT_MIN) * slotPx,
        height: Math.max(MIN_HEIGHT_PX, (placed.item.duration_min / SLOT_MIN) * slotPx - 2),
        left: `calc(${(lane * 100) / lanes}% + 2px)`,
        width: `calc(${100 / lanes}% - 4px)`,
      }}
    >
      <div
        className={cn(
          "group/block relative flex h-full flex-col overflow-hidden border px-2.5 py-1",
          broken
            ? "border-alert/45 bg-alert-bg"
            : own
              ? "border-dashed border-brand/50 bg-brand-bg"
              : "border-border bg-surface",
          isDragging && "z-10 opacity-90 shadow-lift",
        )}
      >
        {readOnly || continued ? null : (
          <ResizeHandle
            edge="top"
            label={`Start ${item.name} earlier or later`}
            onPointerDown={startResize("top")}
          />
        )}

        <div
          ref={setNodeRef}
          {...attributes}
          {...listeners}
          onClick={continued && !readOnly ? onEdit : undefined}
          className={cn(
            "min-h-0 flex-1 touch-none outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            continued ? "cursor-pointer" : "cursor-grab active:cursor-grabbing",
          )}
        >
          <p className="truncate text-[13px] leading-tight font-semibold tracking-[-0.01em]">
            <span className="mr-1.5 font-mono text-[10.5px] font-normal text-faint tabular-nums">
              {continued ? "↳" : hhmm(item.start_min)}
            </span>
            {item.name}
            {short && cost && (
              <span className="ml-1.5 font-mono text-[10.5px] font-normal text-faint">{cost}</span>
            )}
          </p>
          {!short && (
            <p className="truncate font-mono text-[10.5px] text-faint">
              {[
                `${hhmm(item.start_min)}–${until}`,
                cost,
                item.primary_type || item.category,
                block?.open_from && block?.open_to
                  ? `open ${block.open_from}–${block.open_to}`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          {item.description && (
            <p className="mt-0.5 line-clamp-3 text-[11px] leading-[1.35] whitespace-pre-line text-ink-soft">
              {item.description}
            </p>
          )}
        </div>

        {item.reference_url && (
          <a
            href={item.reference_url}
            target="_blank"
            rel="noreferrer"
            onPointerDown={(e) => e.stopPropagation()}
            aria-label={`Open your link for ${item.name}`}
            className={cn(
              "absolute top-0.5 grid size-5 place-items-center rounded text-brand hover:bg-brand-bg",
              readOnly ? "right-0.5" : "right-10.5",
            )}
          >
            <Link2 className="size-3" />
          </a>
        )}

        {!readOnly && (
          <>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={onEdit}
              aria-label={`Edit ${item.name}: time, link and cost`}
              className="absolute top-0.5 right-5.5 grid size-5 place-items-center rounded text-faint opacity-0 transition-opacity group-hover/block:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              <Pencil className="size-3" />
            </button>

            <button
              type="button"
              onClick={onRemove}
              aria-label={`Remove ${item.name}`}
              className="absolute top-0.5 right-0.5 grid size-5 place-items-center rounded text-faint opacity-0 transition-opacity group-hover/block:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              <X className="size-3" />
            </button>

            {endsHere && (
              <ResizeHandle
                edge="bottom"
                label={`Change how long you spend at ${item.name}`}
                onPointerDown={startResize("bottom")}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** Overhangs the block by 3px so the grab zone is bigger than the 8px it looks. */
function ResizeHandle({
  edge,
  label,
  onPointerDown,
}: {
  edge: "top" | "bottom";
  label: string;
  onPointerDown: (e: React.PointerEvent) => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onPointerDown={onPointerDown}
      className={cn(
        "absolute inset-x-0 z-10 h-2.5 cursor-ns-resize touch-none opacity-0 transition-opacity group-hover/block:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50",
        edge === "top" ? "-top-0.5" : "-bottom-0.5",
      )}
    >
      <span
        className={cn(
          "mx-auto block h-0.5 w-8 rounded-full bg-ink/25",
          edge === "top" ? "mt-1" : "mt-1.5",
        )}
      />
    </button>
  );
}
