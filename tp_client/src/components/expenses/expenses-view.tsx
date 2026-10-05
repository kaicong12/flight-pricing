"use client";

// The Expenses tab. One balance panel per currency, then every cost in date order.

import { Pencil, Plus, Search, X } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { FilterChip } from "@/components/ui/filter-chip";
import {
  type Expense,
  type ExpenseDraft,
  type ExpenseTab,
  filterExpenses,
  firstName,
  knownCategories,
  money,
  tagChoices,
} from "@/lib/expense-types";
import { cn } from "@/lib/utils";

import { BalanceBar } from "./balance-bar";
import { ExpenseDialog } from "./expense-dialog";
import { SpendByCategory } from "./spend-by-category";

export function ExpensesView({
  tripId,
  initial,
  meId,
  canEdit,
  defaultDate,
}: {
  tripId: string;
  initial: ExpenseTab;
  meId: string;
  canEdit: boolean;
  defaultDate: string;
}) {
  const [tab, setTab] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ editing: Expense | null } | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const categories = knownCategories(tab.expenses);
  const shown = filterExpenses(tab.expenses, query, category);

  const base = `/api/trips/${encodeURIComponent(tripId)}`;

  const send = useCallback(
    async (path: string, init: RequestInit) => {
      setBusy(true);
      setError(null);
      try {
        const r = await fetch(`${base}${path}`, init);
        if (!r.ok) {
          const body = await r.json().catch(() => null);
          setError(typeof body?.detail === "string" ? body.detail : "That did not save.");
          return;
        }
        const fresh = await fetch(`${base}/expenses`);
        if (fresh.ok) setTab((await fresh.json()) as ExpenseTab);
      } catch {
        setError("Could not reach the planner.");
      } finally {
        setBusy(false);
      }
    },
    [base],
  );

  const json = (body: unknown): RequestInit => ({
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

  const who = (userId: string) => {
    const member = tab.members.find((m) => m.user_id === userId);
    return member ? (userId === meId ? "You" : firstName(member)) : "Someone";
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13.5px] text-muted-foreground">
          Every cost splits between whoever was there. Each currency settles on its own.
        </p>
        {canEdit && (
          <Button size="sm" disabled={busy} onClick={() => setDialog({ editing: null })}>
            <Plus className="size-3.5" /> Add a cost
          </Button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-3.5 rounded-[13px] border border-alert/25 bg-alert-bg px-4 py-3.5">
          <span className="size-1.5 shrink-0 rounded-full bg-alert" />
          <p className="text-[13px] text-alert">{error}</p>
        </div>
      )}

      {tab.balances.length === 0 ? (
        <div className="rounded-card border border-dashed border-border px-5 py-10 text-center">
          <p className="text-[14px] font-medium">Nothing spent yet.</p>
          <p className="mx-auto mt-1.5 max-w-[46ch] text-[13px] leading-[1.55] text-muted-foreground">
            Add what a meal, a ticket or a taxi cost and this fills with who is up and who is down.
            The pencil on any block on the plan screen adds one too.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {tab.balances.map((balance) => (
            <BalanceBar
              key={balance.currency}
              balance={balance}
              members={tab.members}
              meId={meId}
              busy={busy}
              canEdit={canEdit}
              onSettle={(from_user_id, to_user_id, amount_cents) =>
                send(
                  "/settlements",
                  json({
                    from_user_id,
                    to_user_id,
                    amount_cents,
                    currency: balance.currency,
                    paid_on: defaultDate,
                  }),
                )
              }
            />
          ))}
        </div>
      )}

      {tab.expenses.length > 0 && <SpendByCategory expenses={tab.expenses} meId={meId} />}

      {tab.expenses.length > 0 && (
        <section className="overflow-hidden rounded-card border border-border surface shadow-card">
          <div className="space-y-3 border-b border-hairline px-5 py-3.5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase">
                {shown.length === tab.expenses.length
                  ? `${tab.expenses.length} ${tab.expenses.length === 1 ? "cost" : "costs"}`
                  : `${shown.length} of ${tab.expenses.length} costs`}
              </h2>
              <label className="flex h-8 w-full max-w-[260px] items-center gap-2 rounded-[13px] border border-input px-3 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
                <Search className="size-3.5 shrink-0 text-faint" />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Escape" && setQuery("")}
                  placeholder="Search costs"
                  aria-label="Search costs"
                  maxLength={120}
                  className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden"
                />
              </label>
            </div>
            {(categories.length > 0 || category !== null) && (
              <div className="flex flex-wrap gap-1.5">
                <FilterChip active={category === null} onClick={() => setCategory(null)}>
                  All
                </FilterChip>
                {categories.map((c) => {
                  const on = c.toLowerCase() === category?.toLowerCase();
                  return (
                    <FilterChip key={c} active={on} onClick={() => setCategory(on ? null : c)}>
                      {c}
                    </FilterChip>
                  );
                })}
              </div>
            )}
          </div>
          {shown.length === 0 && (
            <p className="px-5 py-6 text-[13px] text-muted-foreground">No cost matches.</p>
          )}
          <ul className="divide-y divide-hairline">
            {shown.map((e) => {
              const mine = e.shares.find((s) => s.user_id === meId);
              return (
                <li key={e.expense_id} className="group flex items-center gap-4 px-5 py-3.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px] font-medium">{e.description}</p>
                    <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">
                      {who(e.payer_id)} paid · {e.spent_on}
                      {e.day_index !== null && ` · day ${e.day_index + 1}`}
                      {e.block_title && ` · ${e.block_title}`}
                      {e.category && ` · ${e.category}`}
                    </p>
                  </div>

                  <div className="shrink-0 text-right">
                    <p className="font-mono text-[13px] tabular-nums">
                      {money(e.amount_cents, e.currency)}
                    </p>
                    {mine && (
                      <p className="mt-0.5 font-mono text-[11.5px] text-faint tabular-nums">
                        you {money(mine.amount_cents, e.currency)}
                      </p>
                    )}
                  </div>

                  {canEdit && (
                    <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <IconButton
                        label={`Edit ${e.description}`}
                        disabled={busy}
                        onClick={() => setDialog({ editing: e })}
                      >
                        <Pencil className="size-3.5" />
                      </IconButton>
                      <IconButton
                        label={`Remove ${e.description}`}
                        disabled={busy}
                        onClick={async () => {
                          const ok = await confirm({
                            title: `Delete “${e.description}”?`,
                            description: `${money(e.amount_cents, e.currency)} and everyone's share of it leave every balance. There is no undo.`,
                            action: "Delete expense",
                          });
                          if (ok) await send(`/expenses/${e.expense_id}`, { method: "DELETE" });
                        }}
                      >
                        <X className="size-3.5" />
                      </IconButton>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {tab.settlements.length > 0 && (
        <section>
          <h2 className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase">
            Payments recorded
          </h2>
          <ul className="mt-2.5 space-y-1.5">
            {tab.settlements.map((s) => (
              <li
                key={s.settlement_id}
                className="group flex items-center gap-3 text-[13px] text-muted-foreground"
              >
                <span className="min-w-0 flex-1 truncate">
                  {who(s.from_user_id)} paid {who(s.to_user_id).toLowerCase()}{" "}
                  <span className="font-mono tabular-nums">
                    {money(s.amount_cents, s.currency)}
                  </span>{" "}
                  on {s.paid_on}
                </span>
                {canEdit && (
                  <IconButton
                    label="Undo this payment"
                    disabled={busy}
                    onClick={async () => {
                      const ok = await confirm({
                        title: "Undo this payment?",
                        description: `${who(s.from_user_id)} paying ${who(s.to_user_id).replace(/^You$/, "you")} ${money(s.amount_cents, s.currency)} is forgotten, and the balances go back to owing it.`,
                        action: "Undo payment",
                      });
                      if (ok) await send(`/settlements/${s.settlement_id}`, { method: "DELETE" });
                    }}
                  >
                    <X className="size-3.5" />
                  </IconButton>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {dialog && (
        <ExpenseDialog
          key={dialog.editing?.expense_id ?? "new"}
          members={tab.members}
          meId={meId}
          currency={dialog.editing?.currency ?? tab.currency}
          defaultDate={defaultDate}
          editing={dialog.editing}
          choices={tagChoices(tab.expenses)}
          onClose={() => setDialog(null)}
          onSubmit={(draft: ExpenseDraft) =>
            send(
              dialog.editing ? `/expenses/${dialog.editing.expense_id}` : "/expenses",
              dialog.editing
                ? { ...json(draft), method: "PUT" }
                : json(draft),
            )
          }
        />
      )}
      {confirmDialog}
    </div>
  );
}

function IconButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid size-7 place-items-center rounded-full text-faint transition-colors hover:bg-page hover:text-ink outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        disabled && "pointer-events-none opacity-40",
      )}
    >
      {children}
    </button>
  );
}
