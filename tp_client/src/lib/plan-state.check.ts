// Checks for planReducer. There is no test runner in tp_client yet, so this is runnable on its own:
// npx tsx src/lib/plan-state.check.ts
//
// It covers the transitions whose failure is invisible until a browser catches it — a hand-added
// place landing where nobody will scroll to it, and the revision guard that stops a late save
// reverting the last drag.

import type { Itinerary, Shortlist, ShortlistPlace } from "./plan-types";
import { cityLabels, initialState, planReducer } from "./plan-state";

function eq(got: unknown, want: unknown, label: string) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) throw new Error(`${label}\n  got  ${a}\n  want ${b}`);
}

function place(place_id: string, name: string, mention_count = 0): ShortlistPlace {
  return {
    place_id,
    city_id: "c-helsinki",
    name,
    address: null,
    lat: 60.17,
    lon: 24.94,
    primary_type: null,
    category: null,
    why_go: null,
    sources: [],
    mention_count,
    in_itinerary: false,
    day_index: null,
  };
}

const itinerary: Itinerary = {
  days: [
    { day_index: 0, date: "2026-12-04", items: [] },
    { day_index: 1, date: "2026-12-05", items: [] },
  ],
};

const shortlist: Shortlist = {
  total: 2,
  shown: 2,
  places: [place("p1", "Mentioned twice", 2), place("p2", "Mentioned once", 1)],
};

const base = initialState(itinerary, shortlist);
const names = (s: { shortlist: ShortlistPlace[] }) => s.shortlist.map((p) => p.name);

// A hand-added place has no mentions, so the server ranks it last. Appending it would put it on a
// page the user is not looking at, which reads as the button doing nothing.
const added = planReducer(base, { type: "placeAdded", place: place("p3", "Added by hand") });
eq(names(added), ["Added by hand", "Mentioned twice", "Mentioned once"], "a new place goes first");
eq(added.total, 3, "a new place raises the denominator");

// Re-adding one already on the list must not double it or inflate the count.
const again = planReducer(added, { type: "placeAdded", place: place("p1", "Mentioned twice", 2) });
eq(names(again), ["Mentioned twice", "Added by hand", "Mentioned once"], "no duplicate row");
eq(again.total, 3, "re-adding does not raise the denominator");

// Adding back something struck off has to clear the dismissal too, or the row stays hidden and the
// add looks like it silently failed.
const struck = planReducer(base, { type: "dismiss", placeId: "p2" });
eq(names(struck), ["Mentioned twice"], "dismiss hides the row");
eq(struck.total, 1, "dismiss lowers the denominator");
const revived = planReducer(struck, { type: "placeAdded", place: place("p2", "Mentioned once", 1) });
eq(revived.dismissed, [], "adding it back clears the dismissal");
eq(names(revived), ["Mentioned once", "Mentioned twice"], "and the row is back");

// Adding a place must not mark any day unsaved: nothing about the itinerary changed.
eq(added.unsaved, [], "adding touches no day");
eq(added.revision, base.revision, "adding does not bump the revision");
eq(added.stale, base.stale, "adding does not re-route anything");

// The revision guard. A save that lands after a further edit describes an older plan.
const withBlock = planReducer(base, {
  type: "add",
  place: place("p1", "Mentioned twice", 2),
  day: 0,
  startMin: 10 * 60,
  durationMin: 60,
});
eq(withBlock.unsaved, [0], "placing a block marks its day unsaved");
eq(withBlock.revision, 1, "placing a block bumps the revision");

// A reference is a link, not an ordering: it must save but never spend a route on the day.
const linked = planReducer(withBlock, {
  type: "reference",
  day: 0,
  placeId: "p1",
  url: "https://airbnb.com/rooms/1",
});
eq(linked.days[0].items[0].reference_url, "https://airbnb.com/rooms/1", "the link is stored");
eq(linked.unsaved, [0], "a link marks the day unsaved");
eq(linked.stale, withBlock.stale, "a link does not re-route the day");
eq(
  planReducer(linked, { type: "reference", day: 0, placeId: "p1", url: "https://airbnb.com/rooms/1" })
    .revision,
  linked.revision,
  "re-saving the same link changes nothing",
);
eq(
  planReducer(linked, { type: "reference", day: 0, placeId: "p1", url: null }).days[0].items[0]
    .reference_url,
  null,
  "clearing the link removes it",
);

const stale = planReducer(withBlock, { type: "saved", days: [0], itinerary, revision: 0 });
eq(stale.unsaved, [0], "a save for an older revision is ignored");
const fresh = planReducer(withBlock, { type: "saved", days: [0], itinerary, revision: 1 });
eq(fresh.unsaved, [], "a save for the current revision clears the day");

const city = (city_id: string, name: string) => ({
  city_id,
  name,
  country: null,
  timezone: null,
});
const hel = city("hel", "Helsinki");
eq(cityLabels([hel]).size, 0, "a one-city trip labels nothing");
eq(
  [...cityLabels([hel, city("sgp", "Singapore")])],
  [
    ["hel", "Helsinki"],
    ["sgp", "Singapore"],
  ],
  "a two-city trip labels both",
);
eq(
  cityLabels([hel, city("sgp", "Singapore")]).get("porto") ?? null,
  null,
  "a place filed under a city the trip does not cover has no label",
);

console.log("plan-state: all checks passed");
