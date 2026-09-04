// Checks for slots.ts. Run: npx tsx src/app/spike/calendar/slots.check.ts

import {
  MIN_DURATION, conflicts, hhmm, layout, resize, slotAt, snap,
} from "./slots";
export function check() {
  const eq = (got: unknown, want: unknown, label: string) => {
    const a = JSON.stringify(got);
    const b = JSON.stringify(want);
    if (a !== b) throw new Error(`${label}\n  got  ${a}\n  want ${b}`);
  };

  eq(snap(614), 600, "snap down");
  eq(snap(616), 630, "snap up");
  eq(slotAt(96, 540, 24), 660, "slotAt: 4 slots of 24px past 09:00");

  const s = { id: "a", name: "A", startMin: 540, durationMin: 60 };
  eq(resize(s, "bottom", 625).durationMin, 90, "bottom edge snaps 10:25 -> 10:30");
  eq(resize(s, "bottom", 545).durationMin, MIN_DURATION, "bottom edge floors at 30 min");
  const top = resize(s, "top", 500);
  eq([top.startMin, top.durationMin], [510, 90], "top edge grows upward, end fixed");
  const squashed = resize(s, "top", 590);
  eq([squashed.startMin, squashed.durationMin], [570, 30], "top edge floors at 30 min, end fixed");

  // Sequential stops share one lane; the cluster is not one wide box.
  eq(layout([
    { id: "a", name: "A", startMin: 540, durationMin: 60 },
    { id: "b", name: "B", startMin: 600, durationMin: 60 },
  ]).map((p) => [p.id, p.lane, p.lanes]), [["a", 0, 1], ["b", 0, 1]], "back to back = one lane");

  // Two overlapping = two lanes; a third, disjoint stop keeps its own full-width cluster.
  eq(layout([
    { id: "a", name: "A", startMin: 540, durationMin: 90 },
    { id: "b", name: "B", startMin: 570, durationMin: 60 },
    { id: "c", name: "C", startMin: 720, durationMin: 30 },
  ]).map((p) => [p.id, p.lane, p.lanes]),
    [["a", 0, 2], ["b", 1, 2], ["c", 0, 1]], "overlap splits, disjoint stays full width");

  // Three-way overlap.
  eq(layout([
    { id: "a", name: "A", startMin: 540, durationMin: 120 },
    { id: "b", name: "B", startMin: 570, durationMin: 90 },
    { id: "c", name: "C", startMin: 600, durationMin: 30 },
  ]).map((p) => [p.id, p.lane, p.lanes]),
    [["a", 0, 3], ["b", 1, 3], ["c", 2, 3]], "three-way overlap = three lanes");

  const walk = (from: string, to: string) => (from === "a" && to === "b" ? 25 : 5);

  // The scenario from the brief: 09:00-10:00 then 10:00, with a 25 minute walk.
  eq(conflicts(
    [{ id: "a", name: "A", startMin: 540, durationMin: 60 },
     { id: "b", name: "B", startMin: 600, durationMin: 60 }],
    walk, { dayStartMin: 480, dayEndMin: 1320 },
  ), [{ code: "travel_does_not_fit", id: "b", fromId: "a", needMin: 25, gapMin: 0 }],
    "travel does not fit");

  // Same pair with the gap the walk needs: silent.
  eq(conflicts(
    [{ id: "a", name: "A", startMin: 540, durationMin: 60 },
     { id: "b", name: "B", startMin: 630, durationMin: 60 }],
    walk, { dayStartMin: 480, dayEndMin: 1320 },
  ), [], "enough gap for the walk");

  eq(conflicts(
    [{ id: "a", name: "A", startMin: 540, durationMin: 60, openFrom: 660, openTo: 1020 }],
    walk, { dayStartMin: 480, dayEndMin: 1320 },
  ), [{ code: "opens_later", id: "a", opensAt: 660, waitMin: 120 }], "opens later");

  eq(conflicts(
    [{ id: "a", name: "A", startMin: 940, durationMin: 60, openFrom: 600, openTo: 960 }],
    walk, { dayStartMin: 480, dayEndMin: 1320 },
  ), [{ code: "closes_before_done", id: "a", closesAt: 960 }], "closes before done");

  eq(conflicts(
    [{ id: "a", name: "A", startMin: 1200, durationMin: 60, outdoor: true }],
    walk, { dayStartMin: 480, dayEndMin: 1320, sunsetMin: 1140 },
  ), [{ code: "after_sunset", id: "a", sunsetMin: 1140 }], "after sunset");

  eq(conflicts(
    [{ id: "a", name: "A", startMin: 1290, durationMin: 60 }],
    walk, { dayStartMin: 480, dayEndMin: 1320 },
  ), [{ code: "outside_day", id: "a" }], "runs past the end of the day");

  eq(hhmm(1290), "21:30", "hhmm");

  console.log("calendar_slots: all checks passed");
}

check();
