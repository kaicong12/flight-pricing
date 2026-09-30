// Checks for the money arithmetic in expense-types.ts. There is no test runner in tp_client, so
// this is runnable on its own: npx tsx src/lib/expense-types.check.ts
//
// It covers the parts a wrong answer hides rather than crashes on — a split that loses a cent, an
// amount box that reads 1.005 as something, and the ordering the balance bar depends on.

import type { CurrencyBalance, Expense } from "./expense-types";
import {
  blockCost,
  costsByBlock,
  forReading,
  money,
  parseAmount,
  splitEvenly,
  widest,
} from "./expense-types";

function eq(got: unknown, want: unknown, label: string) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) throw new Error(`${label}\n  got  ${a}\n  want ${b}`);
}

// An even split always adds back up to what was paid.
for (const amount of [1, 7, 100, 999, 1000, 12345, 100000]) {
  for (let people = 1; people <= 7; people++) {
    const ids = Array.from({ length: people }, (_, i) => `u${i}`);
    const parts = splitEvenly(amount, ids);
    eq(
      parts.reduce((t, p) => t + p.amount_cents, 0),
      amount,
      `split ${amount} between ${people}`,
    );
  }
}

eq(
  splitEvenly(1000, ["a", "b", "c"]),
  [
    { user_id: "a", amount_cents: 334 },
    { user_id: "b", amount_cents: 333 },
    { user_id: "c", amount_cents: 333 },
  ],
  "the odd cent goes to the first participant",
);
eq(splitEvenly(500, []), [], "nobody named splits nothing");

eq(parseAmount("12.50"), 1250, "a plain figure");
eq(parseAmount("1 200"), 120000, "a space as a thousands mark");
eq(parseAmount("1,200.5"), 120050, "a comma as a thousands mark");
eq(parseAmount("40"), 4000, "no decimal point");
eq(parseAmount(".5"), 50, "a leading point");
eq(parseAmount("12.345"), null, "three decimals is not money");
eq(parseAmount("abc"), null, "letters");
eq(parseAmount(""), null, "an empty box");
eq(parseAmount("-5"), null, "a negative cost is not a cost");

eq(money(4000, "EUR"), "40.00 EUR", "a positive figure");
eq(money(-2050, "NOK"), "−20.50 NOK", "a debt reads with a minus, not brackets");

const balance: CurrencyBalance = {
  currency: "EUR",
  total_cents: 9000,
  members: [
    { user_id: "bob", paid_cents: 0, share_cents: 3000, settled_cents: 0, net_cents: -3000 },
    { user_id: "me", paid_cents: 9000, share_cents: 3000, settled_cents: 0, net_cents: 6000 },
    { user_id: "cara", paid_cents: 0, share_cents: 3000, settled_cents: 0, net_cents: -3000 },
  ],
  transfers: [],
};

eq(widest(balance), 6000, "the bars scale to the biggest net");
eq(
  forReading(balance, "me").map((m) => m.user_id),
  ["me", "bob", "cara"],
  "you come first, then the deepest debt",
);
eq(widest({ ...balance, members: [] }), 1, "an empty pile never divides by zero");

const expense = (over: Partial<Expense>): Expense => ({
  expense_id: "e1",
  description: "Dinner",
  amount_cents: 4000,
  currency: "EUR",
  spent_on: "2026-10-05",
  payer_id: "me",
  place_id: null,
  block_id: null,
  block_title: null,
  day_index: null,
  shares: [],
  ...over,
});

const byBlock = costsByBlock([
  expense({ place_id: "p1" }),
  expense({ expense_id: "e2", place_id: "p1", amount_cents: 1500 }),
  expense({ expense_id: "e3", block_id: "b1" }),
  expense({ expense_id: "e4" }),
]);
eq([...byBlock.keys()].sort(), ["b1", "p1"], "a cost with no block is not keyed under one");
eq(byBlock.get("p1")!.length, 2, "a block may be paid for twice");

eq(blockCost(byBlock.get("p1")!), "55.00 EUR", "two costs on one block add up");
eq(
  blockCost([expense({ currency: "EUR" }), expense({ expense_id: "e5", currency: "NOK" })]),
  "40.00 EUR + 40.00 NOK",
  "two currencies on one block are shown apart, never summed",
);

console.log("expense-types.check.ts ok");
