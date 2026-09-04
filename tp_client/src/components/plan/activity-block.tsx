"use client";

// One activity block, positioned on the grid at the time the user pinned it to. Drag the body to
// move it, drag either edge to change how long you spend there.
//
// Warnings sit under the grid rather than inside the block: a block's height is its duration, so
// there is no room to grow into, and the alert border already says which block is the problem.

import { useDraggable } from "@dnd-kit/core";
import { X } from "lucide-react";

import type { PlacedItem, PlanBlock, PlanWarning } from "@/lib/plan-types";
import { DAY_START_MIN, MIN_DURATION, SLOT_MIN, endOf, hhmm, resize, slotAt } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

export function ActivityBlock({
  placed,
  block,
  warnings,
  slotPx,
  onRemove,
  onResize,
}: {
  placed: PlacedItem;
  block: PlanBlock | undefined;
  warnings: PlanWarning[];
  slotPx: number;
  onRemove: () => void;
  onResize: (startMin: number, durationMin: number) => void;
}) {
  const { item, lane, lanes } = placed;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `item:${item.place_id}`,
    data: { kind: "item", item },
  });

  const broken = warnings.length > 0;
  // At the 30-minute minimum there is only room for one line, so the times move to the title.
  const short = item.duration_min <= MIN_DURATION;

  /**
   * Raw pointer events rather than dnd-kit, committed once on pointerup: the board re-routes on
   * every duration change, so dispatching per pixel would spend a computeRoutes call per pixel.
   */
  const startResize = (edge: "top" | "bottom") => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const grid = (e.currentTarget as HTMLElement).closest("[data-grid]")?.getBoundingClientRect();
    if (!grid) return;

    let next = { start_min: item.start_min, duration_min: item.duration_min };
    const move = (ev: PointerEvent) => {
      next = resize(item, edge, slotAt(ev.clientY - grid.top, slotPx));
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
        top: ((item.start_min - DAY_START_MIN) / SLOT_MIN) * slotPx,
        height: (item.duration_min / SLOT_MIN) * slotPx - 2,
        left: `calc(${(lane * 100) / lanes}% + 2px)`,
        width: `calc(${100 / lanes}% - 4px)`,
      }}
    >
      <div
        className={cn(
          "group/block relative flex h-full flex-col overflow-hidden border px-2.5 py-1",
          broken ? "border-alert/45 bg-alert-bg" : "border-border bg-surface",
          isDragging && "z-10 opacity-90 shadow-lift",
        )}
      >
        <ResizeHandle
          edge="top"
          label={`Start ${item.name} earlier or later`}
          onPointerDown={startResize("top")}
        />

        <div
          ref={setNodeRef}
          {...attributes}
          {...listeners}
          className="min-h-0 flex-1 cursor-grab touch-none outline-none focus-visible:ring-3 focus-visible:ring-ring/50 active:cursor-grabbing"
        >
          <p className="truncate text-[13px] leading-tight font-semibold tracking-[-0.01em]">
            <span className="mr-1.5 font-mono text-[10.5px] font-normal text-faint tabular-nums">
              {hhmm(item.start_min)}
            </span>
            {item.name}
          </p>
          {!short && (
            <p className="truncate font-mono text-[10.5px] text-faint">
              {[
                `${hhmm(item.start_min)}–${hhmm(endOf(item))}`,
                item.primary_type || item.category,
                block?.open_from && block?.open_to
                  ? `open ${block.open_from}–${block.open_to}`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${item.name}`}
          className="absolute top-0.5 right-0.5 grid size-5 place-items-center rounded text-faint opacity-0 transition-opacity group-hover/block:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <X className="size-3" />
        </button>

        <ResizeHandle
          edge="bottom"
          label={`Change how long you spend at ${item.name}`}
          onPointerDown={startResize("bottom")}
        />
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
