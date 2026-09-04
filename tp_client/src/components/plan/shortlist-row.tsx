"use client";

// One candidate place. The blurb is a human's opinion from a video or post; the counts are machine
// output, so they are mono.

import { useDraggable } from "@dnd-kit/core";
import { X } from "lucide-react";

import {
  PreviewCard,
  PreviewCardContent,
  PreviewCardTrigger,
} from "@/components/ui/preview-card";
import type { ShortlistPlace } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

export function ShortlistRow({
  place,
  placedDay,
  onDismiss,
}: {
  place: ShortlistPlace;
  placedDay: number | null;
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
          {placedDay !== null && (
            <span className="grid h-6.5 min-w-6.5 place-items-center rounded-full bg-ok-bg px-1.5 font-mono text-[10.5px] text-ok">
              D{placedDay + 1}
            </span>
          )}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <SourceCount place={place} />
      </div>
    </li>
  );
}

function SourceCount({ place }: { place: ShortlistPlace }) {
  const label = place.mention_count === 1 ? "1 source" : `${place.mention_count} sources`;

  if (place.sources.length === 0) {
    return <span className="font-mono text-[11px] text-faint">{label}</span>;
  }

  return (
    <PreviewCard>
      <PreviewCardTrigger
        render={<button type="button" />}
        className="font-mono text-[11px] text-faint underline decoration-dotted decoration-from-font underline-offset-3 transition-colors hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {label}
      </PreviewCardTrigger>
      <PreviewCardContent>
        <ul className="flex flex-col gap-2">
          {place.sources.map((s) => (
            <li key={s.url} className="flex flex-col gap-0.5">
              <span className="font-mono text-[10px] tracking-[0.04em] text-faint uppercase">
                {s.source}
              </span>
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer noopener"
                className="line-clamp-2 text-[12.5px] leading-[1.45] text-ink underline decoration-hairline underline-offset-2 transition-colors hover:decoration-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {s.title}
              </a>
            </li>
          ))}
        </ul>
      </PreviewCardContent>
    </PreviewCard>
  );
}
