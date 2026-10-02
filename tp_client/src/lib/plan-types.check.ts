// Checks for plan-types.ts: npx tsx src/lib/plan-types.check.ts

import type { ItineraryItem } from "./plan-types";
import {
  DAY_START_MIN,
  MIN_DURATION,
  availableWindow,
  endOf,
  endsOn,
  firstFree,
  hhmm,
  keyOf,
  layout,
  piecesOn,
  resize,
  slotAt,
  snap,
  warningText,
} from "./plan-types";

function eq(got: unknown, want: unknown, label: string) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) throw new Error(`${label}\n  got  ${a}\n  want ${b}`);
}

const item = (place_id: string, start_min: number, duration_min = 60): ItineraryItem => ({
  kind: "place",
  place_id,
  block_id: `b-${place_id}`,
  name: place_id.toUpperCase(),
  description: null,
  lat: null,
  lon: null,
  start_min,
  duration_min,
  category: null,
  primary_type: null,
  reference_url: null,
});

const custom = (block_id: string, start_min: number, duration_min = 60): ItineraryItem => ({
  ...item(block_id, start_min, duration_min),
  kind: "custom",
  place_id: null,
  block_id,
});

eq(keyOf(item("p1", 600)), "b-p1", "a place block is its block_id, not its place_id");
eq(keyOf(custom("b1", 600)), "b1", "a custom block is its block_id");

eq(snap(614), 600, "snap down");
eq(snap(616), 630, "snap up");
eq(slotAt(4 * 26, 26), DAY_START_MIN + 120, "slotAt: 4 slots of 26px past the day start");

const a = item("a", 540, 60);
eq(resize(a, "bottom", 625), { start_min: 540, duration_min: 90 }, "bottom snaps 10:25 to 10:30");
eq(resize(a, "bottom", 545), { start_min: 540, duration_min: MIN_DURATION }, "bottom floors at 30");
eq(resize(a, "top", 500), { start_min: 510, duration_min: 90 }, "top grows upward, end fixed");
eq(resize(a, "top", 590), { start_min: 570, duration_min: 30 }, "top floors at 30, end fixed");

eq(resize(a, "bottom", 90, 1440), { start_min: 540, duration_min: 990 }, "last-day bottom adds the offset");

const night = custom("n1", 1350, 460);
const days = [
  { day_index: 0, date: "2026-10-01", items: [] },
  { day_index: 1, date: "2026-10-02", items: [night] },
  { day_index: 2, date: "2026-10-03", items: [item("x", 600)] },
];
eq(
  piecesOn(days, 1).map((p) => [keyOf(p.item), p.offset, p.from, p.to]),
  [["n1", 0, 1350, 1440]],
  "the first day draws up to midnight",
);
eq(
  piecesOn(days, 2).map((p) => [keyOf(p.item), p.offset, p.from, p.to]),
  [["n1", 1440, 0, 370], ["b-x", 0, 600, 660]],
  "the next day draws the tail beside its own blocks",
);
eq(piecesOn(days, 0), [], "nothing reaches back to an earlier day");
eq(endsOn(night, 1), { day: 2, min: 370 }, "an overnight flight lands the next morning");
eq(endsOn(custom("m", 1380, 60), 0), { day: 0, min: 1440 }, "midnight belongs to the day before");

const lanes = (items: ItineraryItem[]) =>
  layout(items).map((p) => [p.item.place_id, p.lane, p.lanes]);

eq(lanes([item("a", 540), item("b", 600)]), [["a", 0, 1], ["b", 0, 1]], "back to back is one lane");
eq(
  lanes([item("a", 540, 90), item("b", 570), item("c", 720, 30)]),
  [["a", 0, 2], ["b", 1, 2], ["c", 0, 1]],
  "overlap splits, a disjoint block stays full width",
);
eq(
  lanes([item("a", 540, 120), item("b", 570, 90), item("c", 600, 30)]),
  [["a", 0, 3], ["b", 1, 3], ["c", 2, 3]],
  "three-way overlap is three lanes",
);
eq(lanes([item("z", 600), item("a", 600)]), [["a", 0, 2], ["z", 1, 2]], "a tie orders by block_id");

eq(endOf(item("a", 600, 90)), 690, "endOf");
eq(hhmm(1290), "21:30", "hhmm");
eq(hhmm(1470), "00:30", "hhmm wraps past midnight");

eq(
  warningText({ code: "closes_before_done", place_id: "b", block_id: "b-b",
                detail: { start: "16:00", need_min: 90, closes: "17:00" } }, "Polar Museum"),
  "Polar Museum — Starts 16:00, needs 90 min, closes 17:00. Move it earlier.",
  "a warning is prefixed with the block's name",
);
eq(warningText({ code: "who_knows", place_id: null, block_id: null, detail: {} }), "who_knows", "unknown code");

const trip = { arrive_time: "13:40:00", depart_time: "17:20:00" };
eq(availableWindow(trip, 0, 4), { from: 820, to: 1440 }, "day 0 starts when the flight lands");
eq(availableWindow(trip, 1, 4), { from: 0, to: 1440 }, "a middle day is unbounded");
eq(availableWindow(trip, 3, 4), { from: 0, to: 1040 }, "the last day ends at departure");
eq(availableWindow(trip, 0, 1), { from: 820, to: 1040 }, "a one-day trip is bounded at both ends");
eq(
  availableWindow({ arrive_time: null, depart_time: null }, 0, 2),
  { from: 0, to: 1440 },
  "no flight times bounds nothing",
);

const open = { from: 0, to: 1440 };
eq(firstFree([], open), 540, "an empty day starts at 09:00");
eq(firstFree(piecesOn(days, 2), open), 540, "a block at 10:00 leaves 09:00 free");
eq(firstFree(piecesOn(days, 2), { from: 570, to: 1440 }), 660, "09:30 arrival skips the 10:00 block");
eq(firstFree([], { from: 435, to: 1440 }), 540, "a 07:15 arrival still waits for 09:00");
eq(firstFree([], { from: 0, to: 480 }), 0, "a day ending at 08:00 falls back to before 09:00");
eq(firstFree(piecesOn(days, 2), { from: 600, to: 660 }), null, "a booked window has no room");
eq(firstFree(piecesOn(days, 2), { from: 0, to: 540 }), 390, "an overnight tail to 06:10 holds the early hours");
eq(firstFree(piecesOn(days, 2), { from: 570, to: 660 }), 570, "half an hour fits when an hour does not");

console.log("plan-types: all checks passed");
