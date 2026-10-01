// Checks for the money arithmetic in expense-types.ts. There is no test runner in tp_client, so
// this is runnable on its own: npx tsx src/lib/expense-types.check.ts
//
// It covers the parts a wrong answer hides rather than crashes on — a split that loses a cent, an
// amount box that reads 1.005 as something, and the ordering the balance bar depends on.

import type { CurrencyBalance, Expense } from "./expense-types";
import {
  OTHER,
  UNTAGGED,
  blockCost,
  colorSlots,
  costsByBlock,
  forReading,
  knownCategories,
  money,
  parseAmount,
  spendByCategory,
  splitEvenly,
  tagChoices,
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
  block_id: null,
  category: null,
  block_title: null,
  day_index: null,
  shares: [],
  ...over,
});

const byBlock = costsByBlock([
  expense({ block_id: "night-1" }),
  expense({ expense_id: "e2", block_id: "night-1", amount_cents: 1500 }),
  expense({ expense_id: "e3", block_id: "night-2" }),
  expense({ expense_id: "e4" }),
]);
eq([...byBlock.keys()].sort(), ["night-1", "night-2"], "a cost with no block is not keyed under one");
eq(byBlock.get("night-1")!.length, 2, "a block may be paid for twice");
eq(byBlock.get("night-2")!.length, 1, "two copies of one place keep their own costs");

eq(blockCost(byBlock.get("night-1")!), "55.00 EUR", "two costs on one block add up");
eq(
  blockCost([expense({ currency: "EUR" }), expense({ expense_id: "e5", currency: "NOK" })]),
  "40.00 EUR + 40.00 NOK",
  "two currencies on one block are shown apart, never summed",
);

const tagged = [
  expense({ category: "Food", amount_cents: 3000, shares: [{ user_id: "me", amount_cents: 1000 }] }),
  expense({ expense_id: "e2", category: "food", amount_cents: 1000 }),
  expense({ expense_id: "e3", category: "Stay", amount_cents: 9000,
            shares: [{ user_id: "me", amount_cents: 4500 }] }),
  expense({ expense_id: "e4", amount_cents: 500 }),
  expense({ expense_id: "e5", category: "Food", currency: "NOK", amount_cents: 99900 }),
];
eq(knownCategories(tagged), ["Food", "Stay"], "one spelling per tag, the most used first");
eq(
  spendByCategory(tagged, "EUR"),
  [
    { key: "stay", label: "Stay", cents: 9000 },
    { key: "food", label: "Food", cents: 4000 },
    { key: UNTAGGED, label: "Untagged", cents: 500 },
  ],
  "a tag's case does not split its slice, and another currency stays out",
);
eq(
  spendByCategory(tagged, "EUR", "me"),
  [
    { key: "stay", label: "Stay", cents: 4500 },
    { key: "food", label: "Food", cents: 1000 },
  ],
  "mine counts only my shares",
);
const many = Array.from({ length: 8 }, (_, i) =>
  expense({ expense_id: `m${i}`, category: `t${i}`, amount_cents: 1000 - i * 100 }),
);
eq(
  spendByCategory(many, "EUR").map((s) => [s.key, s.cents]),
  [["t0", 1000], ["t1", 900], ["t2", 800], ["t3", 700], ["t4", 600], [OTHER, 500 + 400 + 300]],
  "past six slices the smallest fold into Other",
);

eq(
  spendByCategory([expense({ category: "Other" }), expense({ expense_id: "x", amount_cents: 1 })], "EUR")
    .map((s) => s.key),
  ["other", UNTAGGED],
  "a tag typed as Other is its own slice, not the fold",
);
const later = [...many, expense({ expense_id: "late", category: "late", amount_cents: 5000 })];
const slots = colorSlots(spendByCategory(later, "EUR"), later, 6);
eq(slots.get("t0"), 0, "the first tag keeps its colour");
eq(slots.get("late"), 4, "a ninth tag takes the slot its folded neighbour left free");
eq(
  colorSlots(spendByCategory(tagged, "EUR"), tagged, 6).get("stay"),
  colorSlots(spendByCategory(tagged, "EUR", "me"), tagged, 6).get("stay"),
  "Trip and Mine paint a tag alike",
);
eq(
  tagChoices([expense({ category: "food" }), expense({ expense_id: "y", category: "Ferry" })]),
  ["food", "Ferry", "Transport", "Stay", "Activities", "Shopping"],
  "a starter the trip already uses in another case is not offered twice",
);
eq(tagChoices(many).length, 8, "at most eight chips");

console.log("expense-types.check.ts ok");
