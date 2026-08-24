"use client";

// One candidate place. The blurb is a human's opinion from a video or post; the counts are machine
// output, so they are mono.

import { useDraggable } from "@dnd-kit/core";
import { Plus, X } from "lucide-react";

import type { ShortlistPlace } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

export function ShortlistRow({
  place,
  placedDay,
  onAdd,
  onDismiss,
}: {
  place: ShortlistPlace;
  placedDay: number | null;
  onAdd: () => void;
  onDismiss: () => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `shortlist:${place.place_id}`,
    data: { kind: "shortlist", place },
  });

  return (
    <li
      ref={setNodeRef}
      className={cn(
        "group relative border-b border-hairline px-5 py-4 last:border-b-0",
        isDragging && "opacity-40",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div
          {...listeners}
          {...attributes}
          className="min-w-0 flex-1 cursor-grab touch-none active:cursor-grabbing"
        >
          <p className="text-[14px] leading-snug font-semibold tracking-[-0.01em]">{place.name}</p>
          {place.why_go && (
            <p className="mt-1 line-clamp-2 text-[13px] leading-[1.5] text-muted-foreground">
              {place.why_go}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onDismiss}
            aria-label={`Remove ${place.name} from the shortlist`}
            className="grid size-6 place-items-center rounded-full text-faint opacity-0 transition-all group-hover:opacity-100 hover:bg-alert-bg hover:text-alert focus-visible:opacity-100 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <X className="size-3.5" />
          </button>
          {placedDay === null ? (
            <button
              type="button"
              onClick={onAdd}
              aria-label={`Add ${place.name} to the day`}
              className="grid size-6.5 place-items-center rounded-full border border-border bg-surface text-ink-soft transition-colors hover:border-ink hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Plus className="size-3.5" />
            </button>
          ) : (
            <span className="grid h-6.5 min-w-6.5 place-items-center rounded-full bg-ok-bg px-1.5 font-mono text-[10.5px] text-ok">
              D{placedDay + 1}
            </span>
          )}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {place.sources.length > 0 && (
          <span className="flex h-5.5 items-center rounded-full bg-page px-2 font-mono text-[10.5px] tracking-[0.03em] text-ink-soft">
            {place.sources.join(" · ")}
          </span>
        )}
        <span className="font-mono text-[11px] text-faint">
          {place.mention_count === 1 ? "1 source" : `${place.mention_count} sources`}
        </span>
        {place.rating !== null && (
          <span className="font-mono text-[11px] text-faint">
            {place.rating.toFixed(1)}
            {place.rating_count ? ` (${place.rating_count.toLocaleString("en-GB")})` : ""}
          </span>
        )}
      </div>
    </li>
  );
}
