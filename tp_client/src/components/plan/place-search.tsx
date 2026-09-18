"use client";

// Adding a place the ingestion never named: search Google's venues near the city, then say what it
// is for. Both are required — the category has nowhere else to come from with no mentions to derive.

import { useEffect, useState } from "react";
import { CheckIcon, PlusIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { VenueSuggestion } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 250;
const MIN_CHARS = 2;

export function PlaceSearch({
  tripId,
  categories,
  onAdd,
}: {
  tripId: string;
  categories: string[];
  onAdd: (placeId: string, category: string) => Promise<string | null>;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<VenueSuggestion | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<{ q: string; items: VenueSuggestion[] }>({
    q: "",
    items: [],
  });

  const q = query.trim();
  const settled = results.q === q;
  const suggestions = settled ? results.items : [];
  const searching = q.length >= MIN_CHARS && !settled;

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      if (q.length < MIN_CHARS) {
        setResults({ q, items: [] });
        return;
      }
      try {
        const r = await fetch(`/api/trips/${tripId}/places?q=${encodeURIComponent(q)}`, {
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
  }, [q, tripId, open]);

  function reset() {
    setQuery("");
    setPicked(null);
    setCategory(null);
    setError(null);
    setResults({ q: "", items: [] });
  }

  async function submit() {
    if (!picked || !category) return;
    setSaving(true);
    const failure = await onAdd(picked.place_id, category);
    setSaving(false);
    if (failure) {
      setError(failure);
      return;
    }
    setOpen(false);
    reset();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger className="mt-3 flex h-9 w-full items-center gap-2 rounded-[13px] border border-dashed border-input px-3 text-left text-[13px] text-muted-foreground transition-colors hover:border-[#c6bda4] hover:text-ink outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50">
        <PlusIcon className="size-3.5 shrink-0 opacity-50" />
        Add a place yourself
      </DialogTrigger>

      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>Add a place</DialogTitle>
          <DialogDescription>
            Anything the videos missed. Search this city, then say what it is for.
          </DialogDescription>
        </DialogHeader>

        {/* min-w-0: a grid item defaults to min-width:auto, so the nowrap suggestion lines below
            would widen the dialog instead of being truncated by it. */}
        <div className="min-w-0 space-y-4">
          <div className="min-w-0 space-y-2">
            <Input
              autoFocus
              value={picked ? picked.name : query}
              onChange={(e) => {
                setPicked(null);
                setQuery(e.target.value);
              }}
              placeholder="Search for a place"
              aria-label="Search for a place"
            />

            {picked ? (
              <p className="flex items-start gap-1.5 px-1 text-[12.5px] text-muted-foreground">
                <CheckIcon className="mt-0.5 size-3.5 shrink-0 text-ok" />
                {picked.context ?? "Selected"}
              </p>
            ) : q.length < MIN_CHARS ? (
              <p className="px-1 text-[12.5px] text-faint">Type at least two letters.</p>
            ) : searching ? (
              <p className="px-1 text-[12.5px] text-faint">Searching…</p>
            ) : suggestions.length === 0 ? (
              <p className="px-1 text-[12.5px] text-faint">Nothing found near this city.</p>
            ) : (
              <ul className="max-h-52 overflow-y-auto rounded-card-sm border border-border">
                {suggestions.map((s) => (
                  <li key={s.place_id} className="min-w-0">
                    <button
                      type="button"
                      onClick={() => setPicked(s)}
                      className="block w-full min-w-0 border-b border-hairline px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-page outline-none focus-visible:bg-page"
                    >
                      <span className="block truncate text-[13.5px]">{s.name}</span>
                      {s.context && (
                        <span className="block truncate text-[12px] text-faint">{s.context}</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <fieldset className="space-y-2">
            <legend className="text-[13px] font-semibold">What is it for?</legend>
            <div className="flex flex-wrap gap-1.5">
              {categories.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-pressed={category === c}
                  onClick={() => setCategory(c)}
                  className={cn(
                    "flex h-7 items-center rounded-full px-3 text-[12.5px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    category === c
                      ? "bg-ink text-primary-foreground"
                      : "bg-page text-muted-foreground hover:text-ink",
                  )}
                >
                  {c}
                </button>
              ))}
            </div>
          </fieldset>

          {error && <p className="text-[12.5px] text-alert">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="lg" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button size="lg" disabled={!picked || !category || saving} onClick={submit}>
            {saving ? "Adding…" : "Add to shortlist"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
