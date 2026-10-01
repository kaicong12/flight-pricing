"use client";

// Where the money went, one donut per currency since they never combine. Trip is everything anyone
// paid; Mine is only your shares.

import { type PieArcDatum, arc, pie } from "d3-shape";
import { useState } from "react";

import { FilterChip } from "@/components/ui/filter-chip";
import {
  type Expense,
  type Slice,
  knownCategories,
  money,
  spendByCategory,
} from "@/lib/expense-types";
import { cn } from "@/lib/utils";

// Validated with the dataviz palette checker against the light surface.
const COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
const NEUTRAL = "#a8a59b";
const SIZE = 168;
const OUTER = SIZE / 2;
const INNER = OUTER * 0.62;

const layout = pie<Slice>()
  .value((s) => s.cents)
  .sort(null);
const path = arc<PieArcDatum<Slice>>().innerRadius(INNER).outerRadius(OUTER).cornerRadius(2);

export function SpendByCategory({ expenses, meId }: { expenses: Expense[]; meId: string }) {
  const [mine, setMine] = useState(false);
  const order = knownCategories(expenses).map((c) => c.toLowerCase());
  const colorOf = (category: string) => {
    const i = order.indexOf(category.toLowerCase());
    return i >= 0 && i < COLORS.length ? COLORS[i] : NEUTRAL;
  };
  const currencies = [...new Set(expenses.map((e) => e.currency))];

  return (
    <section className="rounded-card border border-border surface p-5 shadow-card">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase">
          Spend by category
        </h2>
        <div className="flex gap-1.5">
          <FilterChip active={!mine} onClick={() => setMine(false)}>
            Trip
          </FilterChip>
          <FilterChip active={mine} onClick={() => setMine(true)}>
            Mine
          </FilterChip>
        </div>
      </div>

      <div className="mt-4 grid gap-6 md:grid-cols-2">
        {currencies.map((currency) => (
          <Donut
            key={currency}
            currency={currency}
            slices={spendByCategory(expenses, currency, mine ? meId : null)}
            colorOf={colorOf}
          />
        ))}
      </div>
    </section>
  );
}

function Donut({
  currency,
  slices,
  colorOf,
}: {
  currency: string;
  slices: Slice[];
  colorOf: (category: string) => string;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const total = slices.reduce((t, s) => t + s.cents, 0);
  const shown = slices.find((s) => s.category === hover);

  if (total === 0) {
    return <p className="text-[13px] text-muted-foreground">Nothing of yours in {currency}.</p>;
  }

  return (
    <div className="flex items-center gap-5">
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`${-OUTER} ${-OUTER} ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`Spend in ${currency} by category`}
        className="shrink-0"
        onPointerLeave={() => setHover(null)}
      >
        {layout(slices).map((a) => (
          <path
            key={a.data.category}
            d={path(a) ?? ""}
            fill={colorOf(a.data.category)}
            stroke="var(--surface)"
            strokeWidth={2}
            tabIndex={0}
            aria-label={`${a.data.category} ${money(a.data.cents, currency)}`}
            onPointerEnter={() => setHover(a.data.category)}
            onFocus={() => setHover(a.data.category)}
            onBlur={() => setHover(null)}
            className={cn(
              "outline-none transition-opacity",
              hover && hover !== a.data.category && "opacity-35",
            )}
          />
        ))}
        <text textAnchor="middle" y={-2} className="fill-ink font-mono text-[13px] font-semibold">
          {money(shown?.cents ?? total, currency)}
        </text>
        <text textAnchor="middle" y={16} className="fill-faint text-[11px]">
          {shown ? shown.category : "total"}
        </text>
      </svg>

      <ul className="min-w-0 flex-1 space-y-1.5">
        {slices.map((s) => (
          <li
            key={s.category}
            onPointerEnter={() => setHover(s.category)}
            onPointerLeave={() => setHover(null)}
            className={cn(
              "flex items-center gap-2 text-[12.5px] transition-opacity",
              hover && hover !== s.category && "opacity-50",
            )}
          >
            <span
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ background: colorOf(s.category) }}
            />
            <span className="min-w-0 flex-1 truncate">{s.category}</span>
            <span className="font-mono text-ink-soft tabular-nums">
              {money(s.cents, currency)}
            </span>
            <span className="w-9 text-right font-mono text-faint tabular-nums">
              {Math.round((s.cents / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
