// Mirrors tp_backend/tp_api/expenses/schemas.py. Amounts are minor units of their own currency.

import type { Member } from "./api-types";

export type ExpenseShare = { user_id: string; amount_cents: number };

export type Expense = {
  expense_id: string;
  description: string;
  amount_cents: number;
  currency: string;
  spent_on: string;
  payer_id: string;
  block_id: string | null;
  category: string | null;
  block_title: string | null;
  day_index: number | null;
  shares: ExpenseShare[];
};

export type Settlement = {
  settlement_id: string;
  from_user_id: string;
  to_user_id: string;
  amount_cents: number;
  currency: string;
  paid_on: string;
};

/** Positive is owed back to them, negative is what they owe. Per currency, and always sums to 0. */
export type MemberBalance = {
  user_id: string;
  paid_cents: number;
  share_cents: number;
  settled_cents: number;
  net_cents: number;
};

export type Transfer = { from_user_id: string; to_user_id: string; amount_cents: number };

export type CurrencyBalance = {
  currency: string;
  total_cents: number;
  members: MemberBalance[];
  transfers: Transfer[];
};

export type ExpenseTab = {
  currency: string;
  members: Member[];
  expenses: Expense[];
  settlements: Settlement[];
  balances: CurrencyBalance[];
};

export type ExpenseDraft = {
  description: string;
  amount_cents: number;
  currency: string;
  spent_on: string;
  payer_id: string;
  block_id: string | null;
  category: string | null;
  participants: string[];
  shares: ExpenseShare[];
};

export const CURRENCIES = ["EUR", "NOK", "SEK", "DKK", "GBP", "USD", "CHF", "PLN", "CZK", "ISK",
                           "SGD", "MYR", "JPY", "KRW", "THB", "IDR", "VND", "AUD", "CAD", "CNY",
                           "HKD", "TWD", "NZD", "PHP"];

/** An even split whose parts add up exactly — the odd minor units go to the first participants. */
export function splitEvenly(amountCents: number, userIds: string[]): ExpenseShare[] {
  if (!userIds.length) return [];
  const base = Math.floor(amountCents / userIds.length);
  const odd = amountCents - base * userIds.length;
  return userIds.map((user_id, i) => ({ user_id, amount_cents: base + (i < odd ? 1 : 0) }));
}

/** Minor units to a typed figure. Returns null for anything that is not a number. */
export function parseAmount(text: string): number | null {
  const cleaned = text.replace(/[\s,]/g, "");
  if (!/^\d*\.?\d{0,2}$/.test(cleaned) || cleaned === "" || cleaned === ".") return null;
  return Math.round(Number(cleaned) * 100);
}

export function money(cents: number, currency: string): string {
  const figure = (Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${cents < 0 ? "−" : ""}${figure} ${currency}`;
}

/** First name, which is what fits in a bar label and a column head. */
export function firstName(member: { name: string | null; email: string }): string {
  return (member.name?.trim() || member.email).split(/[\s@]/)[0];
}

/** The widest net in a pile, so every bar in it is drawn to one scale. */
export function widest(balance: CurrencyBalance): number {
  return Math.max(1, ...balance.members.map((m) => Math.abs(m.net_cents)));
}

/** Your row first, then the biggest debts — you are what you came to the tab to read. */
export function forReading(balance: CurrencyBalance, meId: string): MemberBalance[] {
  return [...balance.members].sort((a, b) => {
    if (a.user_id === meId) return -1;
    if (b.user_id === meId) return 1;
    return a.net_cents - b.net_cents;
  });
}

/** What each block has cost so far, keyed the way `keyOf` keys a block. */
export function costsByBlock(expenses: Expense[]): Map<string, Expense[]> {
  const out = new Map<string, Expense[]>();
  for (const e of expenses) {
    if (e.block_id) out.set(e.block_id, [...(out.get(e.block_id) ?? []), e]);
  }
  return out;
}

/** One chip's worth of text for a block: a total per currency, since they never combine. */
export function blockCost(expenses: Expense[]): string {
  const totals = new Map<string, number>();
  for (const e of expenses) totals.set(e.currency, (totals.get(e.currency) ?? 0) + e.amount_cents);
  return [...totals].map(([currency, cents]) => money(cents, currency)).join(" + ");
}

export function knownCategories(expenses: Expense[]): string[] {
  const counts = new Map<string, { label: string; n: number }>();
  for (const e of expenses) {
    if (!e.category) continue;
    const key = e.category.toLowerCase();
    const seen = counts.get(key);
    counts.set(key, { label: seen?.label ?? e.category, n: (seen?.n ?? 0) + 1 });
  }
  return [...counts.values()].sort((a, b) => b.n - a.n).map((c) => c.label);
}

const STARTER_TAGS = ["Food", "Transport", "Stay", "Activities", "Shopping"];

export function tagChoices(expenses: Expense[]): string[] {
  const known = knownCategories(expenses);
  const seen = new Set(known.map((c) => c.toLowerCase()));
  return [...known, ...STARTER_TAGS.filter((c) => !seen.has(c.toLowerCase()))].slice(0, 8);
}

export const UNTAGGED = "\u0000untagged";
export const OTHER = "\u0000other";

const SLICES = 6;

export type Slice = { key: string; label: string; cents: number };

/** Each tag's colour slot: the trip's first `n` tags keep theirs for good, a later one takes a slot
 * this donut leaves free. Untagged and Other take none. */
export function colorSlots(slices: Slice[], expenses: Expense[], n: number): Map<string, number> {
  const order = [...new Set(expenses.filter((e) => e.category).map((e) => e.category!.toLowerCase()))];
  const out = new Map<string, number>();
  for (const s of slices) {
    const i = order.indexOf(s.key);
    if (i >= 0 && i < n) out.set(s.key, i);
  }
  const used = new Set(out.values());
  let free = 0;
  for (const s of slices) {
    if (out.has(s.key) || s.key === UNTAGGED || s.key === OTHER) continue;
    while (used.has(free)) free++;
    if (free >= n) break;
    used.add(free);
    out.set(s.key, free);
  }
  return out;
}

/** One currency's spend by tag, largest first; `meId` counts only that person's shares. Past six
 * slices the smallest fold into Other. */
export function spendByCategory(
  expenses: Expense[],
  currency: string,
  meId: string | null = null,
): Slice[] {
  const labels = new Map(knownCategories(expenses).map((c) => [c.toLowerCase(), c]));
  const totals = new Map<string, number>();
  for (const e of expenses) {
    if (e.currency !== currency) continue;
    const cents = meId
      ? (e.shares.find((s) => s.user_id === meId)?.amount_cents ?? 0)
      : e.amount_cents;
    if (cents <= 0) continue;
    const key = e.category ? e.category.toLowerCase() : UNTAGGED;
    totals.set(key, (totals.get(key) ?? 0) + cents);
  }
  const slices = [...totals]
    .map(([key, cents]) => ({ key, label: labels.get(key) ?? "Untagged", cents }))
    .sort((a, b) => b.cents - a.cents);
  if (slices.length <= SLICES) return slices;
  const rest = slices.slice(SLICES - 1).reduce((t, s) => t + s.cents, 0);
  return [...slices.slice(0, SLICES - 1), { key: OTHER, label: "Other", cents: rest }];
}
