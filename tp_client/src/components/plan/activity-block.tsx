"use client";

// One activity block, positioned on the grid at the time the user pinned it to. Drag the body to
// move it earlier or later within its own day, drag either edge to change how long you spend there.
// Use the X to take it off the day; there is no drag that moves it to another one.
//
// Warnings sit under the grid rather than inside the block: a block's height is its duration, so
// there is no room to grow into, and the alert border already says which block is the problem.

import { useState } from "react";

import { useDraggable } from "@dnd-kit/core";
import { Link2, Pencil, X } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { PlacedItem, PlanBlock, PlanWarning } from "@/lib/plan-types";
import {
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

export function ActivityBlock({
  placed,
  block,
  warnings,
  slotPx,
  readOnly,
  onRemove,
  onReference,
  onResize,
  onEdit,
}: {
  placed: PlacedItem;
  block: PlanBlock | undefined;
  warnings: PlanWarning[];
  slotPx: number;
  readOnly: boolean;
  onRemove: () => void;
  onReference: (url: string | null) => void;
  onResize: (startMin: number, durationMin: number) => void;
  /** Given for a custom block only: a place's name and type are Google's, not the user's. */
  onEdit?: () => void;
}) {
  const { item, lane, lanes } = placed;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `item:${keyOf(item)}`,
    data: { kind: "item", item },
    disabled: readOnly,
  });
  const own = item.kind === "custom";

  const broken = warnings.length > 0;
  // At the 30-minute minimum there is only room for one line, so the times move to the title.
  const short = item.duration_min <= MIN_DURATION;

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
          broken
            ? "border-alert/45 bg-alert-bg"
            : own
              ? "border-dashed border-brand/50 bg-brand-bg"
              : "border-border bg-surface",
          isDragging && "z-10 opacity-90 shadow-lift",
        )}
      >
        {readOnly ? null : (
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
          {item.description && (
            <p className="mt-0.5 line-clamp-3 text-[11px] leading-[1.35] whitespace-pre-line text-ink-soft">
              {item.description}
            </p>
          )}
        </div>

        {readOnly ? (
          item.reference_url ? (
            <a
              href={item.reference_url}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open your link for ${item.name}`}
              className="absolute top-0.5 right-0.5 grid size-5 place-items-center rounded text-brand hover:bg-brand-bg"
            >
              <Link2 className="size-3" />
            </a>
          ) : null
        ) : (
          <>
            {onEdit && (
              <button
                type="button"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={onEdit}
                aria-label={`Edit ${item.name}`}
                className="absolute top-0.5 right-10.5 grid size-5 place-items-center rounded text-faint opacity-0 transition-opacity group-hover/block:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                <Pencil className="size-3" />
              </button>
            )}

            <Reference name={item.name} url={item.reference_url} onSave={onReference} />

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
          </>
        )}
      </div>
    </div>
  );
}

/** The user's own link for this block: a booking confirmation, a listing, an email receipt. */
function Reference({
  name,
  url,
  onSave,
}: {
  name: string;
  url: string | null;
  onSave: (url: string | null) => void;
}) {
  const [draft, setDraft] = useState(url ?? "");
  const [open, setOpen] = useState(false);
  const trimmed = draft.trim();
  const valid = trimmed === "" || /^https?:\/\/\S+$/.test(trimmed);

  const save = () => {
    if (!valid) return;
    onSave(trimmed || null);
    setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setDraft(url ?? "");
      }}
    >
      <PopoverTrigger
        aria-label={url ? `Edit your link for ${name}` : `Add a link for ${name}`}
        // The block body is draggable, so the press must not reach it.
        onPointerDown={(e) => e.stopPropagation()}
        className={cn(
          "absolute top-0.5 right-5.5 grid size-5 place-items-center rounded transition-opacity focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50",
          url
            ? "text-brand hover:bg-brand-bg"
            : "text-faint opacity-0 group-hover/block:opacity-100 hover:text-ink",
        )}
      >
        <Link2 className="size-3" />
      </PopoverTrigger>

      <PopoverContent align="end" className="gap-2">
        <label className="text-[12px] font-medium text-ink-soft" htmlFor={`ref-${name}`}>
          Your link for {name}
        </label>
        <input
          id={`ref-${name}`}
          type="url"
          value={draft}
          autoFocus
          placeholder="https://airbnb.com/… or a booking email"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          className="h-9 rounded-lg border border-input bg-transparent px-2.5 text-[13px] outline-none placeholder:text-faint focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <div className="flex items-center justify-between gap-2">
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="text-[12px] font-medium text-brand underline"
            >
              Open
            </a>
          ) : (
            <span className="text-[12px] text-faint">Only you and the trip see this.</span>
          )}
          <button
            type="button"
            onClick={save}
            disabled={!valid}
            className="h-8 rounded-full bg-ink px-3 text-[12.5px] font-medium text-primary-foreground hover:bg-ink-hover disabled:opacity-50"
          >
            {trimmed ? "Save" : "Clear"}
          </button>
        </div>
      </PopoverContent>
    </Popover>
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
