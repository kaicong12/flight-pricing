"use client";

// The left column: every place the ingestion found, ranked by how many independent sources named it.

import type { ShortlistPlace } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

import { ShortlistRow } from "./shortlist-row";

const CATEGORIES = ["eat", "see", "do", "drink", "buy"];

export function ShortlistPanel({
  places,
  total,
  placedDays,
  category,
  loading,
  onCategory,
  onAdd,
  onDismiss,
  onMore,
}: {
  places: ShortlistPlace[];
  total: number;
  placedDays: Map<string, number>;
  category: string | null;
  loading: boolean;
  onCategory: (category: string | null) => void;
  onAdd: (place: ShortlistPlace) => void;
  onDismiss: (place: ShortlistPlace) => void;
  onMore: () => void;
}) {
  return (
    <section className="flex max-h-[calc(100dvh-140px)] flex-col overflow-hidden rounded-card border border-border surface shadow-card">
      <div className="border-b border-border px-5 pt-4.5 pb-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Shortlist</h2>
          <span className="font-mono text-[11px] text-faint">
            {places.length} of {total} shown
          </span>
        </div>
        <p className="mt-1.5 text-[12.5px] leading-[1.5] text-muted-foreground">
          Ranked by how many independent sources mentioned it. Add one to a day, then drag to order.
        </p>

        <div className="mt-3.5 flex flex-wrap gap-1.5">
          <FilterChip active={category === null} onClick={() => onCategory(null)}>
            All
          </FilterChip>
          {CATEGORIES.map((c) => (
            <FilterChip key={c} active={category === c} onClick={() => onCategory(c)}>
              {c}
            </FilterChip>
          ))}
        </div>
      </div>

      {places.length === 0 ? (
        <p className="px-5 py-8 text-[13.5px] text-muted-foreground">
          {loading
            ? "Loading the shortlist…"
            : category
              ? `Nothing tagged ${category} yet.`
              : "No places yet. The ingestion may still be running."}
        </p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {places.map((place) => (
            <ShortlistRow
              key={place.place_id}
              place={place}
              placedDay={placedDays.get(place.place_id) ?? null}
              onAdd={() => onAdd(place)}
              onDismiss={() => onDismiss(place)}
            />
          ))}
        </ul>
      )}

      {places.length < total && !category && (
        <button
          type="button"
          onClick={onMore}
          className="shrink-0 border-t border-border px-5 py-3 font-mono text-[11px] tracking-[0.04em] text-faint uppercase transition-colors hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {loading ? "Loading…" : `Show more (${total - places.length} left)`}
        </button>
      )}
    </section>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex h-6 items-center rounded-full px-2.5 text-[12px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        active
          ? "bg-ink text-primary-foreground"
          : "bg-page text-muted-foreground hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
