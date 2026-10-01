// Mirrors tp_backend/tp_api/expenses/schemas.py, plus the arithmetic the forms need before a save.
//
// Every amount is minor units of its own currency. Nothing here adds two currencies together: a
// trip that spent in NOK and EUR has two balances, and neither needs a rate.

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
