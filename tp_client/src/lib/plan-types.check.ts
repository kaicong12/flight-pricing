// Checks for the grid maths in plan-types.ts. There is no test runner in tp_client yet, so this is
// runnable on its own: npx tsx src/lib/plan-types.check.ts
//
// It covers the parts that fail silently — lane packing, edge resizing against the 30-minute floor,
// and snapping — because a wrong answer here just draws a block in the wrong place.

import type { ItineraryItem } from "./plan-types";
import {
  DAY_START_MIN,
  MIN_DURATION,
  availableWindow,
  endOf,
  hhmm,
  layout,
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
  place_id,
  name: place_id.toUpperCase(),
  lat: null,
  lon: null,
  start_min,
  duration_min,
  category: null,
  primary_type: null,
});

eq(snap(614), 600, "snap down");
eq(snap(616), 630, "snap up");
eq(slotAt(4 * 26, 26), DAY_START_MIN + 120, "slotAt: 4 slots of 26px past the day start");

const a = item("a", 540, 60);
eq(resize(a, "bottom", 625), { start_min: 540, duration_min: 90 }, "bottom snaps 10:25 to 10:30");
eq(resize(a, "bottom", 545), { start_min: 540, duration_min: MIN_DURATION }, "bottom floors at 30");
eq(resize(a, "top", 500), { start_min: 510, duration_min: 90 }, "top grows upward, end fixed");
eq(resize(a, "top", 590), { start_min: 570, duration_min: 30 }, "top floors at 30, end fixed");

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
eq(lanes([item("z", 600), item("a", 600)]), [["a", 0, 2], ["z", 1, 2]], "a tie orders by place_id");

eq(endOf(item("a", 600, 90)), 690, "endOf");
eq(hhmm(1290), "21:30", "hhmm");
eq(hhmm(1470), "00:30", "hhmm wraps past midnight");

// The warning the pinned model added. Both directions read as English.
eq(
  warningText({ code: "travel_does_not_fit", place_id: "b",
                detail: { from: "Polar Museum", to: "Raketten", need_min: 25, gap_min: 0 } }),
  "Only 0 min after Polar Museum, but it is a 25 min trip.",
  "travel_does_not_fit, positive gap",
);
eq(
  warningText({ code: "travel_does_not_fit", place_id: "b",
                detail: { from: "Polar Museum", to: "Raketten", need_min: 5, gap_min: -30 } }),
  "Overlaps Polar Museum, and the 5 min trip between them is not possible.",
  "travel_does_not_fit, overlap",
);

// The flight window. Day 0 cannot start before landing; the last day cannot run past departure.
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

console.log("plan-types: all checks passed");
