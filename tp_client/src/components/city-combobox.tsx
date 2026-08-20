"use client";

// City typeahead. The visible text is the suggestion description; the value handed upward is the
// Google place_id, because a typed string is not an identity.

import { useEffect, useState } from "react";
import { ChevronsUpDownIcon } from "lucide-react";

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { CitySuggestion } from "@/lib/api-types";

const DEBOUNCE_MS = 250;

type Props = {
  selected: CitySuggestion | null;
  onSelect: (city: CitySuggestion | null) => void;
};

export function CityCombobox({ selected, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Results are stamped with the query they answer, so "loading" is derived rather than a second
  // piece of state set synchronously inside the effect.
  const [results, setResults] = useState<{ q: string; items: CitySuggestion[] }>({
    q: "",
    items: [],
  });

  const q = query.trim();
  const settled = results.q === q;
  const suggestions = settled ? results.items : [];
  const loading = q.length >= 2 && !settled;

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      if (q.length < 2) {
        setResults({ q, items: [] });
        return;
      }
      try {
        const r = await fetch(`/api/cities?q=${encodeURIComponent(q)}`, {
          signal: controller.signal,
        });
        setResults({ q, items: r.ok ? await r.json() : [] });
      } catch {
        // An aborted keystroke is not a failure; the next one owns the result.
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        id="city"
        className="flex h-11 w-full items-center justify-between rounded-lg border border-input bg-white px-3 text-left text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span className={cn(!selected && "text-muted-foreground")}>
          {selected ? selected.description : "Helsinki"}
        </span>
        <ChevronsUpDownIcon className="size-4 shrink-0 opacity-40" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-(--anchor-width) p-0">
        <Command shouldFilter={false}>
          <CommandInput
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder="Search for a city"
          />
          <CommandList>
            <CommandEmpty className="text-muted-foreground">
              {q.length < 2
                ? "Type at least two letters."
                : loading
                  ? "Searching…"
                  : "No cities found."}
            </CommandEmpty>
            {suggestions.map((s) => (
              <CommandItem
                key={s.place_id}
                value={s.place_id}
                onSelect={() => {
                  onSelect(s);
                  setOpen(false);
                }}
              >
                {s.description}
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
