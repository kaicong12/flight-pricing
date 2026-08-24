"use client";

// One activity block. The start time is derived from the order and never edited directly — the user
// moves the block, we recompute the clock. Duration is theirs to set.

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Minus, Plus, X } from "lucide-react";

import type { ItineraryItem, PlanBlock, PlanWarning } from "@/lib/plan-types";
import { warningText } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

const STEP_MIN = 15;

export function ActivityBlock({
  item,
  block,
  warnings,
  index,
  onRemove,
  onDuration,
}: {
  item: ItineraryItem;
  block: PlanBlock | undefined;
  warnings: PlanWarning[];
  index: number;
  onRemove: () => void;
  onDuration: (minutes: number) => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: `item:${item.place_id}`, data: { kind: "item", item } });

  const broken = warnings.length > 0;

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        "relative rounded-card-sm border bg-surface transition-colors",
        broken ? "border-warn-border" : "border-border",
        isDragging && "z-10 opacity-90 shadow-lift",
      )}
    >
      <div className="flex items-start gap-3 px-4 py-3.5">
        <span className="mt-px w-11 shrink-0 font-mono text-[12.5px] text-ink-soft tabular-nums">
          {block?.start ?? "--:--"}
        </span>

        <div className="min-w-0 flex-1">
          <p className="text-[14px] leading-snug font-semibold tracking-[-0.01em]">
            <span className="mr-1.5 font-mono text-[11px] text-faint">{index + 1}</span>
            {item.name}
          </p>
          <p className="mt-1 font-mono text-[11px] text-faint">
            {[
              item.primary_type || item.category,
              `${item.duration_min} min`,
              block?.open_from && block?.open_to
                ? `open ${block.open_from}–${block.open_to}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-0.5">
          <StepButton
            label={`Shorten ${item.name}`}
            disabled={item.duration_min <= STEP_MIN}
            onClick={() => onDuration(Math.max(STEP_MIN, item.duration_min - STEP_MIN))}
          >
            <Minus className="size-3" />
          </StepButton>
          <StepButton
            label={`Lengthen ${item.name}`}
            onClick={() => onDuration(item.duration_min + STEP_MIN)}
          >
            <Plus className="size-3" />
          </StepButton>
          <StepButton label={`Remove ${item.name}`} onClick={onRemove}>
            <X className="size-3.5" />
          </StepButton>
          <button
            ref={setActivatorNodeRef}
            {...listeners}
            {...attributes}
            aria-label={`Reorder ${item.name}`}
            className="grid size-6 cursor-grab touch-none place-items-center rounded text-faint transition-colors hover:text-ink active:cursor-grabbing outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <GripVertical className="size-3.5" />
          </button>
        </div>
      </div>

      {warnings.map((w) => (
        <div
          key={`${w.code}:${w.place_id}`}
          className="mx-4 mb-3.5 flex items-start gap-2.5 rounded-[13px] bg-alert-bg px-3.5 py-2.5"
        >
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-alert" />
          <p className="text-[12.5px] leading-[1.45] text-alert">{warningText(w)}</p>
        </div>
      ))}
    </div>
  );
}

function StepButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="grid size-6 place-items-center rounded text-faint transition-colors hover:text-ink disabled:opacity-30 disabled:hover:text-faint outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {children}
    </button>
  );
}
