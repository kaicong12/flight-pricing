"use client";

// Where the money went, one donut per currency. Trip is everything anyone paid; Mine is your shares.

import { type PieArcDatum, arc, pie } from "d3-shape";
import { useState } from "react";

import { FilterChip } from "@/components/ui/filter-chip";
import {
  type Expense,
  OTHER,
  type Slice,
  UNTAGGED,
  colorSlots,
  money,
  spendByCategory,
} from "@/lib/expense-types";
import { cn } from "@/lib/utils";

// Validated with the dataviz palette checker against the light surface.
const COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
const UNTAGGED_COLOR = "#8a877e";
const OTHER_COLOR = "#c9c6bc";
const SIZE = 168;
const OUTER = SIZE / 2;
const INNER = OUTER * 0.62;

const layout = pie<Slice>()
  .value((s) => s.cents)
  .sort(null);
const path = arc<PieArcDatum<Slice>>().innerRadius(INNER).outerRadius(OUTER).cornerRadius(2);

export function SpendByCategory({ expenses, meId }: { expenses: Expense[]; meId: string }) {
  const [mine, setMine] = useState(false);
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
            expenses={expenses}
          />
        ))}
      </div>
    </section>
  );
}

function Donut({
  currency,
  slices,
  expenses,
}: {
  currency: string;
  slices: Slice[];
  expenses: Expense[];
}) {
  const [hover, setHover] = useState<string | null>(null);
  const total = slices.reduce((t, s) => t + s.cents, 0);
  const shown = slices.find((s) => s.key === hover);
  const slots = colorSlots(slices, expenses, COLORS.length);
  const colorOf = (key: string) =>
    key === UNTAGGED ? UNTAGGED_COLOR : key === OTHER ? OTHER_COLOR : COLORS[slots.get(key) ?? 0];

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
            key={a.data.key}
            d={path(a) ?? ""}
            fill={colorOf(a.data.key)}
            stroke="var(--surface)"
            strokeWidth={2}
            tabIndex={0}
            aria-label={`${a.data.label} ${money(a.data.cents, currency)}`}
            onPointerEnter={() => setHover(a.data.key)}
            onFocus={() => setHover(a.data.key)}
            onBlur={() => setHover(null)}
            className={cn(
              "outline-none transition-opacity",
              hover && hover !== a.data.key && "opacity-35",
            )}
          />
        ))}
        <text textAnchor="middle" y={-2} className="fill-ink font-mono text-[13px] font-semibold">
          {money(shown?.cents ?? total, currency)}
        </text>
        <text textAnchor="middle" y={16} className="fill-faint text-[11px]">
          {shown ? shown.label : "total"}
        </text>
      </svg>

      <ul className="min-w-0 flex-1 space-y-1.5">
        {slices.map((s) => (
          <li
            key={s.key}
            onPointerEnter={() => setHover(s.key)}
            onPointerLeave={() => setHover(null)}
            className={cn(
              "flex items-center gap-2 text-[12.5px] transition-opacity",
              hover && hover !== s.key && "opacity-50",
            )}
          >
            <span
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ background: colorOf(s.key) }}
            />
            <span className="min-w-0 flex-1 truncate">{s.label}</span>
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
