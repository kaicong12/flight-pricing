"use client";

// Asks the worker to draft the empty days. The handler leaves a day with blocks on it alone, so this
// can never overwrite the user's ordering — but new blocks appearing unannounced is still a surprise,
// so a calendar that already has anything on it gets warned first.

import { Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DRAFT_PENDING, type TripStatus, errorText } from "@/lib/api-types";
import type { ItineraryDay } from "@/lib/plan-types";
import { formatDayTab } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;
// Three Gemini rounds behind a 4s throttle gap, plus the queue's 2s poll. Well clear of the worst case.
const MAX_POLL_MS = 3 * 60 * 1000;

export function DraftPlan({ tripId, days }: { tripId: string; days: ItineraryDay[] }) {
  const [open, setOpen] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const taken = days.filter((d) => d.items.length > 0);
  const empty = days.filter((d) => d.items.length === 0);

  async function draft() {
    setOpen(false);
    setDrafting(true);
    setError(null);
    try {
      const r = await fetch(`/api/trips/${encodeURIComponent(tripId)}/draft`, { method: "POST" });
      if (!r.ok) {
        setError(errorText(await r.json().catch(() => null), r.status));
        setDrafting(false);
        return;
      }
      await waitForDraft(tripId);
      // The days are written straight to the database by the worker, and the board's reducer owns
      // its own copy, so re-reading the page is the only way to show them.
      window.location.reload();
    } catch {
      setError("Could not reach the server.");
      setDrafting(false);
    }
  }

  // Nothing to fill: the button would queue a task that returns "every day already has items".
  if (empty.length === 0 && !drafting) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <button
        type="button"
        onClick={() => (taken.length > 0 ? setOpen(true) : draft())}
        disabled={drafting}
        className={cn(
          "flex h-9 items-center gap-1.5 rounded-full border border-border bg-surface px-3.5 text-[13px] font-medium text-ink transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          "hover:border-[#c6bda4] disabled:opacity-60",
        )}
      >
        <Sparkles
          className={cn(
            "size-3.5",
            drafting && "animate-[tp-pulse_1.4s_ease-in-out_infinite] motion-reduce:animate-none",
          )}
        />
        {drafting ? "Drafting…" : "Draft my days"}
      </button>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {taken.length === 1
              ? "1 day already has blocks"
              : `${taken.length} days already have blocks`}
          </DialogTitle>
          <DialogDescription>
            {listDays(taken)} {taken.length === 1 ? "is" : "are"} yours and will be left exactly as
            you arranged {taken.length === 1 ? "it" : "them"}. Only {listDays(empty)} will be filled.
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-[13px] leading-[1.5] text-alert">{error}</p>}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button onClick={draft}>
            Draft {empty.length === 1 ? "1 day" : `${empty.length} days`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** "Fri 12 Sep, Sat 13 Sep and Sun 14 Sep" — the same labels as the day tabs. */
function listDays(days: ItineraryDay[]): string {
  const names = days.map((d) => formatDayTab(d.date));
  if (names.length <= 1) return names[0] ?? "no days";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** Polls until route.plan reaches a terminal status. Resolves either way — the reload shows whatever
 * the draft managed, and a draft that failed leaves the days empty rather than wrong. */
async function waitForDraft(tripId: string): Promise<void> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < MAX_POLL_MS) {
    await new Promise((done) => setTimeout(done, POLL_MS));
    const r = await fetch(`/api/trips/${encodeURIComponent(tripId)}`);
    if (!r.ok) continue;
    const body = (await r.json()) as TripStatus;
    if (!DRAFT_PENDING.includes(body.draft ?? "")) return;
  }
}
