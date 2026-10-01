"use client";

import { FilterChip } from "@/components/ui/filter-chip";
import { Input } from "@/components/ui/input";

const CATEGORY_MAX = 40;

export function CategoryPicker({
  value,
  choices,
  onChange,
  onEnter,
}: {
  value: string;
  choices: string[];
  onChange: (category: string) => void;
  onEnter?: () => void;
}) {
  const current = value.trim().toLowerCase();
  return (
    <div className="space-y-2">
      <Input
        value={value}
        maxLength={CATEGORY_MAX}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
        placeholder="Tag it — food, transport, stay"
        aria-label="Category"
      />
      <div className="flex flex-wrap gap-1.5">
        {choices.map((c) => {
          const on = c.toLowerCase() === current;
          return (
            <FilterChip key={c} active={on} onClick={() => onChange(on ? "" : c)}>
              {c}
            </FilterChip>
          );
        })}
      </div>
    </div>
  );
}
