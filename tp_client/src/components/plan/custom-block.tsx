"use client";

// A block the shortlist could never hold: a flight, a hotel night, a booked activity.

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CategoryPicker } from "@/components/expenses/category-picker";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { CURRENCIES, parseAmount } from "@/lib/expense-types";
import type { CustomDraft } from "@/lib/plan-state";
import {
  DAY_END_MIN,
  type ItineraryDay,
  type ItineraryItem,
  endsOn,
  formatDayTab,
  hhmm,
} from "@/lib/plan-types";

const TITLE_MAX = 120;
const DESCRIPTION_MAX = 1000;

/** `amountCents` null clears every cost on the block. */
export type CostEntry = { amountCents: number | null; currency: string; category: string | null };

export type BlockExtras = { url: string | null; cost: CostEntry | null };

function minutes(text: string): number | null {
  const m = /^(\d{2}):(\d{2})$/.exec(text);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/** Mounted only while open, so the caller's `key` is what resets it rather than an effect. */
export function CustomBlockDialog({
  dayIndex,
  startMin,
  days,
  windowOf,
  editing,
  cost,
  currency,
  tags,
  onClose,
  onSubmit,
}: {
  /** The day the block starts on. */
  dayIndex: number;
  /** The clicked half hour when adding. */
  startMin: number;
  days: ItineraryDay[];
  windowOf: (day: number) => { from: number; to: number };
  editing: ItineraryItem | null;
  cost: string | null;
  currency: string;
  tags: string[];
  onClose: () => void;
  /** A place block's draft keeps Google's name; only its description is the user's. */
  onSubmit: (
    draft: CustomDraft,
    startMin: number,
    durationMin: number,
    extras: BlockExtras,
  ) => void;
}) {
  const own = !editing || editing.kind === "custom";
  const until = editing
    ? endsOn(editing, dayIndex)
    : { day: dayIndex, min: Math.min(startMin + 60, windowOf(dayIndex).to) };

  const [title, setTitle] = useState(editing?.name ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [start, setStart] = useState(hhmm(editing?.start_min ?? startMin));
  const [end, setEnd] = useState(hhmm(until.min));
  const [endDay, setEndDay] = useState(until.day);
  const [url, setUrl] = useState(editing?.reference_url ?? "");
  const [amount, setAmount] = useState("");
  const [picked, setPicked] = useState(currency);
  const [category, setCategory] = useState("");
  const [clearCost, setClearCost] = useState(false);

  const trimmed = title.trim();
  const startAt = minutes(start);
  const endAt = minutes(end);
  const duration =
    startAt === null || endAt === null
      ? null
      : (endDay - dayIndex) * DAY_END_MIN + endAt - startAt;

  const link = url.trim();
  const cents = parseAmount(amount.trim());

  const problem = (() => {
    if (startAt === null || endAt === null || duration === null) return "Pick a start and an end.";
    if (link && !/^https?:\/\/\S+$/.test(link)) return "A link starts with http:// or https://.";
    if (amount.trim() && !(cents && cents > 0)) return "A cost is a figure like 12.50.";
    if (duration <= 0) return "It has to end after it starts.";
    const first = windowOf(dayIndex);
    if (startAt < first.from) return `That day only starts at ${hhmm(first.from)}.`;
    if (endAt > windowOf(endDay).to) return `That day ends at ${hhmm(windowOf(endDay).to)}.`;
    return null;
  })();

  const save = () => {
    if ((own && !trimmed) || problem || startAt === null || duration === null) return;
    const entry = cents
      ? { amountCents: cents, currency: picked, category: category.trim() || null }
      : clearCost
        ? { amountCents: null, currency: picked, category: null }
        : null;
    onSubmit(
      { title: own || !editing ? trimmed : editing.name, description: description.trim() || null },
      startAt,
      duration,
      { url: link || null, cost: entry },
    );
    onClose();
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>
            {editing ? (own ? "Edit block" : editing.name) : `Add a block at ${hhmm(startMin)}`}
          </DialogTitle>
          <DialogDescription>
            {own
              ? "A flight, a stay, anything booked. It is yours — nothing checks it against opening hours."
              : "Set the exact minutes you will be there. It can run into the next day."}
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4">
          {own && (
            <Input
              autoFocus
              value={title}
              maxLength={TITLE_MAX}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              placeholder="Flight SQ 3116 to Oslo"
              aria-label="What is this block"
            />
          )}

          <Textarea
            value={description}
            maxLength={DESCRIPTION_MAX}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={
              own
                ? "Booking reference, terminal, address, who to ask for"
                : "A note to yourself — why here, why at this time"
            }
            aria-label="Details"
            className="min-h-20 text-[13.5px]"
          />

          <fieldset className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2">
            <legend className="sr-only">When</legend>
            <span className="text-[13px] font-semibold">Starts</span>
            <div className="flex items-center gap-2">
              <Input
                type="time"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                aria-label="Start time"
                className="w-32 font-mono tabular-nums"
              />
              <span className="text-[12.5px] text-muted-foreground">
                {formatDayTab(days[dayIndex]?.date ?? "")}
              </span>
            </div>

            <span className="text-[13px] font-semibold">Ends</span>
            <div className="flex items-center gap-2">
              <Input
                type="time"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                aria-label="End time"
                className="w-32 font-mono tabular-nums"
              />
              <select
                value={endDay}
                aria-label="End day"
                onChange={(e) => setEndDay(Number(e.target.value))}
                className="h-8 min-w-0 rounded-lg border border-input bg-transparent px-1.5 text-[12.5px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {days
                  .filter((d) => d.day_index >= dayIndex)
                  .map((d) => (
                    <option key={d.day_index} value={d.day_index}>
                      Day {d.day_index + 1} · {formatDayTab(d.date)}
                    </option>
                  ))}
              </select>
            </div>
          </fieldset>

          <Input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            placeholder="Your link — a booking, a listing, a receipt"
            aria-label="Link"
          />

          <fieldset className="space-y-2">
            <div className="flex items-baseline justify-between gap-3">
              <legend className="text-[13px] font-semibold">Cost</legend>
              {cost && (
                <button
                  type="button"
                  onClick={() => {
                    setClearCost(!clearCost);
                    setAmount("");
                  }}
                  className="text-[12.5px] text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {clearCost ? `keep ${cost}` : `so far ${cost} · clear`}
                </button>
              )}
            </div>
            <div className="flex gap-1.5">
              <Input
                value={amount}
                disabled={clearCost}
                inputMode="decimal"
                placeholder={cost ? "Add another 0.00" : "0.00"}
                onChange={(e) => setAmount(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && save()}
                aria-label="What it cost"
                className="min-w-0 flex-1 font-mono tabular-nums"
              />
              <select
                value={picked}
                aria-label="Currency"
                onChange={(e) => setPicked(e.target.value)}
                className="h-8 rounded-lg border border-input bg-transparent px-1.5 font-mono text-[12.5px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {[...new Set([currency, ...CURRENCIES])].map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            {amount.trim() && (
              <CategoryPicker
                value={category}
                choices={tags}
                onChange={setCategory}
                onEnter={save}
              />
            )}
            <p className="text-[12px] text-faint">
              {clearCost
                ? "Every cost on this block goes when you save."
                : "Split evenly, you paid. The Expenses tab changes either."}
            </p>
          </fieldset>

          {problem && <p className="text-[12.5px] text-alert">{problem}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="lg" onClick={onClose}>
            Cancel
          </Button>
          <Button size="lg" disabled={(own && !trimmed) || problem !== null} onClick={save}>
            {editing ? "Save" : "Add to day"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
