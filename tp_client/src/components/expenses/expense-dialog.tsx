"use client";

// One cost: what it was, who paid, and who it splits between. Mounted only while open so the
// caller's `key` resets it rather than an effect.

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
import { Input } from "@/components/ui/input";
import type { Member } from "@/lib/api-types";
import {
  CURRENCIES,
  type Expense,
  type ExpenseDraft,
  firstName,
  money,
  parseAmount,
  splitEvenly,
} from "@/lib/expense-types";
import { cn } from "@/lib/utils";

const DESCRIPTION_MAX = 200;
const SELECT =
  "h-9 rounded-input border border-input bg-surface px-2.5 text-[13.5px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

export function ExpenseDialog({
  members,
  meId,
  currency: defaultCurrency,
  defaultDate,
  editing,
  block,
  onClose,
  onSubmit,
}: {
  members: Member[];
  meId: string;
  currency: string;
  defaultDate: string;
  editing: Expense | null;
  /** Prefilled when the `$` on a block opened this, so the cost lands on that block. */
  block?: { block_id: string; title: string };
  onClose: () => void;
  onSubmit: (draft: ExpenseDraft) => void;
}) {
  const [description, setDescription] = useState(editing?.description ?? block?.title ?? "");
  const [amount, setAmount] = useState(
    editing ? (editing.amount_cents / 100).toFixed(2) : "",
  );
  const [currency, setCurrency] = useState(editing?.currency ?? defaultCurrency);
  const [spentOn, setSpentOn] = useState(editing?.spent_on ?? defaultDate);
  const [payerId, setPayerId] = useState(editing?.payer_id ?? meId);
  const [exact, setExact] = useState(false);
  const [picked, setPicked] = useState<string[]>(
    editing ? editing.shares.map((s) => s.user_id) : members.map((m) => m.user_id),
  );
  const [typed, setTyped] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (editing?.shares ?? []).map((s) => [s.user_id, (s.amount_cents / 100).toFixed(2)]),
    ),
  );

  const amountCents = parseAmount(amount);
  const participants = members.filter((m) => picked.includes(m.user_id));
  const exactCents = participants.map((m) => parseAmount(typed[m.user_id] ?? "") ?? 0);
  const claimed = exactCents.reduce((t, c) => t + c, 0);
  const left = (amountCents ?? 0) - claimed;

  const valid =
    description.trim().length > 0 &&
    amountCents !== null &&
    amountCents > 0 &&
    participants.length > 0 &&
    (!exact || left === 0);

  const preview = amountCents !== null && participants.length > 0 && !exact
    ? splitEvenly(amountCents, picked)[0].amount_cents
    : null;

  const save = () => {
    if (!valid || amountCents === null) return;
    onSubmit({
      description: description.trim(),
      amount_cents: amountCents,
      currency,
      spent_on: spentOn,
      payer_id: payerId,
      block_id: editing?.block_id ?? block?.block_id ?? null,
      participants: exact ? [] : picked,
      shares: exact
        ? participants.map((m, i) => ({ user_id: m.user_id, amount_cents: exactCents[i] }))
        : [],
    });
    onClose();
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit cost" : "Add a cost"}</DialogTitle>
          <DialogDescription>
            {block
              ? `What ${block.title} cost, and who it splits between.`
              : "Each currency is its own pile — nothing is converted."}
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4">
          <Input
            autoFocus
            value={description}
            maxLength={DESCRIPTION_MAX}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            placeholder="Dinner at Löyly"
            aria-label="What was it"
          />

          <div className="flex gap-2">
            <Input
              value={amount}
              inputMode="decimal"
              onChange={(e) => setAmount(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              placeholder="0.00"
              aria-label="How much"
              className="flex-1 font-mono tabular-nums"
            />
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              aria-label="Currency"
              className={cn(SELECT, "w-[92px] font-mono")}
            >
              {[...new Set([currency, ...CURRENCIES])].map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          <div className="flex gap-2">
            <select
              value={payerId}
              onChange={(e) => setPayerId(e.target.value)}
              aria-label="Who paid"
              className={cn(SELECT, "min-w-0 flex-1")}
            >
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.user_id === meId ? "You paid" : `${firstName(m)} paid`}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={spentOn}
              onChange={(e) => setSpentOn(e.target.value)}
              aria-label="When"
              className={cn(SELECT, "font-mono")}
            />
          </div>

          <fieldset className="space-y-2">
            <div className="flex items-baseline justify-between gap-3">
              <legend className="text-[13px] font-semibold">Split between</legend>
              <button
                type="button"
                onClick={() => setExact(!exact)}
                className="text-[12.5px] text-muted-foreground underline decoration-dotted underline-offset-2 transition-colors hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {exact ? "split evenly instead" : "enter exact amounts"}
              </button>
            </div>

            <ul className="space-y-1.5">
              {members.map((m) => {
                const on = picked.includes(m.user_id);
                return (
                  <li key={m.user_id} className="flex items-center gap-2.5">
                    <label className="flex min-w-0 flex-1 items-center gap-2.5 text-[13.5px]">
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() =>
                          setPicked(
                            on
                              ? picked.filter((id) => id !== m.user_id)
                              : [...picked, m.user_id],
                          )
                        }
                        className="size-4 accent-[var(--ink)]"
                      />
                      <span className="truncate">
                        {m.user_id === meId ? "You" : firstName(m)}
                      </span>
                    </label>
                    {exact && on && (
                      <Input
                        value={typed[m.user_id] ?? ""}
                        inputMode="decimal"
                        onChange={(e) => setTyped({ ...typed, [m.user_id]: e.target.value })}
                        placeholder="0.00"
                        aria-label={`${firstName(m)}'s share`}
                        className="h-8 w-[104px] font-mono text-[13px] tabular-nums"
                      />
                    )}
                  </li>
                );
              })}
            </ul>

            <p className="text-[12.5px] text-muted-foreground">
              {exact ? (
                left === 0 ? (
                  "The shares add up."
                ) : (
                  <span className="text-alert">
                    {money(Math.abs(left), currency)} {left > 0 ? "still unassigned" : "over"}
                  </span>
                )
              ) : preview !== null ? (
                `${money(preview, currency)} each`
              ) : (
                "Pick at least one person."
              )}
            </p>
          </fieldset>
        </div>

        <DialogFooter>
          <Button variant="ghost" size="lg" onClick={onClose}>
            Cancel
          </Button>
          <Button size="lg" disabled={!valid} onClick={save}>
            {editing ? "Save" : "Add cost"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
