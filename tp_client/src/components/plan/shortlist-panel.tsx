"use client";

// The left column: every place the ingestion found, ranked by how many independent sources named it.

import { ListFilter, Search, X } from "lucide-react";
import { useId, useRef } from "react";

import { FilterChip } from "@/components/ui/filter-chip";
import { Kbd } from "@/components/ui/kbd";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { City } from "@/lib/api-types";
import type { ShortlistPlace, ShortlistSource } from "@/lib/plan-types";
import { cityColor } from "@/lib/trips";
import { useShortcut } from "@/lib/use-shortcut";
import { cn } from "@/lib/utils";

import { PlaceSearch } from "./place-search";
import { ShortlistRow } from "./shortlist-row";

const CATEGORIES = ["eat", "see", "do", "drink", "buy"];
const SOURCES: { id: ShortlistSource; label: string }[] = [
  { id: "youtube", label: "YouTube" },
  { id: "rednote", label: "RedNote" },
];

export function ShortlistPanel({
  places,
  total,
  placedDays,
  readOnly,
  category,
  loading,
  tripId,
  onCategory,
  source,
  onSource,
  cities,
  city,
  onCity,
  search,
  searched,
  onSearch,
  onDismiss,
  onAdd,
  onMore,
}: {
  places: ShortlistPlace[];
  total: number;
  placedDays: Map<string, number[]>;
  readOnly: boolean;
  category: string | null;
  loading: boolean;
  tripId: string;
  onCategory: (category: string | null) => void;
  /** Null is every source, which is also the only filter that keeps a place added by hand. */
  source: ShortlistSource | null;
  onSource: (source: ShortlistSource | null) => void;
  cities: City[];
  city: string | null;
  onCity: (city: string | null) => void;
  search: string;
  /** The search the list on screen answers, which trails `search` by a debounce. */
  searched: string;
  onSearch: (search: string) => void;
  onDismiss: (place: ShortlistPlace) => void;
  onAdd: (placeId: string, category: string) => Promise<string | null>;
  onMore: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  useShortcut("k", () => {
    input.current?.focus();
    input.current?.select();
  });

  const narrowed = [
    cities.find((c) => c.city_id === city)?.name,
    SOURCES.find((x) => x.id === source)?.label,
  ].filter(Boolean);

  return (
    <section className="flex max-h-[calc(100dvh-140px)] flex-col overflow-hidden rounded-card border border-border surface shadow-card">
      <div className="border-b border-border px-5 pt-4.5 pb-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Shortlist</h2>
          <span className="font-mono text-[11px] text-faint">
            {places.length} of {total} shown
          </span>
        </div>
        {narrowed.length > 0 && (
          <button
            type="button"
            onClick={() => {
              onCity(null);
              onSource(null);
            }}
            aria-label="Clear the city and source filters"
            className="mt-1 flex items-center gap-1 font-mono text-[11px] text-ink-soft transition-colors hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {narrowed.join(" · ")}
            <X className="size-3" />
          </button>
        )}
        <p className="mt-1.5 text-[12.5px] leading-[1.5] text-muted-foreground">
          Ranked by how many independent sources mentioned it. Add one to a day, then drag to order.
        </p>

        <label className="mt-3.5 flex h-9 items-center gap-2 rounded-[13px] border border-input px-3 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
          <Search className="size-3.5 shrink-0 text-faint" />
          <input
            ref={input}
            type="search"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              onSearch("");
              e.currentTarget.blur();
            }}
            placeholder="Search the shortlist"
            aria-label="Search the shortlist"
            maxLength={120}
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden"
          />
          {!search && <Kbd letter="K" />}
        </label>

        <div className="mt-3 flex items-start gap-2">
          <div className="flex flex-1 flex-wrap gap-1.5">
            <FilterChip active={category === null} onClick={() => onCategory(null)}>
              All
            </FilterChip>
            {CATEGORIES.map((c) => (
              <FilterChip key={c} active={category === c} onClick={() => onCategory(c)}>
                {c}
              </FilterChip>
            ))}
          </div>
          <MoreFilters
            source={source}
            onSource={onSource}
            cities={cities}
            city={city}
            onCity={onCity}
            active={narrowed.length}
          />
        </div>

        {!readOnly && (
          <PlaceSearch tripId={tripId} categories={CATEGORIES} onAdd={onAdd} />
        )}
      </div>

      {places.length === 0 ? (
        <p className="px-5 py-8 text-[13.5px] text-muted-foreground">
          {loading
            ? "Loading the shortlist…"
            : searched
              ? `Nothing on the shortlist matches “${searched}”.`
              : category || source || city
              ? `Nothing ${category ? `tagged ${category} ` : ""}${
                  source ? `from ${SOURCES.find((x) => x.id === source)?.label} ` : ""
                }${city ? `in ${cities.find((c) => c.city_id === city)?.name} ` : ""}yet.`
              : "No places yet. The ingestion may still be running."}
        </p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {places.map((place) => (
            <ShortlistRow
              key={place.place_id}
              place={place}
              placedDays={placedDays.get(place.place_id) ?? []}
              cityName={place.city_name}
              readOnly={readOnly}
              onDismiss={() => onDismiss(place)}
            />
          ))}
        </ul>
      )}

      {places.length < total && (
        <button
          type="button"
          onClick={onMore}
          disabled={loading}
          className="shrink-0 border-t border-border px-5 py-3 font-mono text-[11px] tracking-[0.04em] text-faint uppercase transition-colors hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {loading ? "Loading…" : `Show more (${total - places.length} left)`}
        </button>
      )}
    </section>
  );
}

/** Both source boxes ticked is no source filter; the last ticked box cannot be cleared. */
function MoreFilters({
  source,
  onSource,
  cities,
  city,
  onCity,
  active,
}: {
  source: ShortlistSource | null;
  onSource: (source: ShortlistSource | null) => void;
  cities: City[];
  city: string | null;
  onCity: (city: string | null) => void;
  active: number;
}) {
  const radios = useId();
  const ticked = (id: ShortlistSource) => source === null || source === id;
  const toggle = (id: ShortlistSource) => {
    const other = SOURCES.find((s) => s.id !== id)!.id;
    onSource(ticked(id) ? other : null);
  };

  return (
    <Popover>
      <PopoverTrigger
        aria-label={active ? `${active} more ${active === 1 ? "filter" : "filters"} on` : "More filters"}
        className={cn(
          "flex h-6 shrink-0 items-center justify-center gap-1 rounded-full transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          active
            ? "bg-ink px-2 text-primary-foreground"
            : "w-6 bg-page text-muted-foreground hover:text-ink",
        )}
      >
        <ListFilter className="size-3.5" />
        {active ? <span className="font-mono text-[11px]">{active}</span> : null}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-52 gap-1.5">
        {cities.length > 1 && (
          <fieldset className="mb-1.5 flex flex-col gap-1.5">
            <legend className="mb-1.5 text-[12px] font-medium text-ink-soft">City</legend>
            {[null, ...cities].map((c) => (
              <label key={c?.city_id ?? "all"} className="flex items-center gap-2 text-[13px]">
                <input
                  type="radio"
                  name={radios}
                  checked={city === (c?.city_id ?? null)}
                  onChange={() => onCity(c?.city_id ?? null)}
                  className="size-3.5 accent-ink"
                />
                {c && (
                  <span
                    className="size-1.5 shrink-0 rounded-full"
                    style={{ background: cityColor(cities, c.city_id) ?? undefined }}
                  />
                )}
                <span className="truncate">{c?.name ?? "All cities"}</span>
              </label>
            ))}
          </fieldset>
        )}
        <p className="text-[12px] font-medium text-ink-soft">Named by</p>
        {SOURCES.map((s) => (
          <label key={s.id} className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={ticked(s.id)}
              disabled={source === s.id}
              onChange={() => toggle(s.id)}
              className="size-3.5 accent-ink"
            />
            {s.label}
          </label>
        ))}
      </PopoverContent>
    </Popover>
  );
}
