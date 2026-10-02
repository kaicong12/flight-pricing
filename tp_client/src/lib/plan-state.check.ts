// Checks for planReducer: npx tsx src/lib/plan-state.check.ts

import type { Itinerary, Shortlist, ShortlistPlace } from "./plan-types";
import { keyOf } from "./plan-types";
import { customItem, initialState, placedDays, planReducer } from "./plan-state";

function eq(got: unknown, want: unknown, label: string) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) throw new Error(`${label}\n  got  ${a}\n  want ${b}`);
}

function place(place_id: string, name: string, mention_count = 0): ShortlistPlace {
  return {
    place_id,
    city_name: "Helsinki",
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

const added = planReducer(base, { type: "placeAdded", place: place("p3", "Added by hand") });
eq(names(added), ["Added by hand", "Mentioned twice", "Mentioned once"], "a new place goes first");
eq(added.total, 3, "a new place raises the denominator");

const again = planReducer(added, { type: "placeAdded", place: place("p1", "Mentioned twice", 2) });
eq(names(again), ["Mentioned twice", "Added by hand", "Mentioned once"], "no duplicate row");
eq(again.total, 3, "re-adding does not raise the denominator");

const struck = planReducer(base, { type: "dismiss", placeId: "p2" });
eq(names(struck), ["Mentioned twice"], "dismiss hides the row");
eq(struck.total, 1, "dismiss lowers the denominator");
const revived = planReducer(struck, { type: "placeAdded", place: place("p2", "Mentioned once", 1) });
eq(revived.dismissed, [], "adding it back clears the dismissal");
eq(names(revived), ["Mentioned once", "Mentioned twice"], "and the row is back");

eq(added.unsaved, [], "adding touches no day");
eq(added.revision, base.revision, "adding does not bump the revision");
eq(added.stale, base.stale, "adding does not re-route anything");

const withBlock = planReducer(base, {
  type: "add",
  place: place("p1", "Mentioned twice", 2),
  day: 0,
  startMin: 10 * 60,
  durationMin: 60,
});
eq(withBlock.unsaved, [0], "placing a block marks its day unsaved");
eq(withBlock.revision, 1, "placing a block bumps the revision");
const p1Key = keyOf(withBlock.days[0].items[0]);

const secondNight = planReducer(withBlock, {
  type: "add",
  place: place("p1", "Mentioned twice", 2),
  day: 1,
  startMin: 10 * 60,
  durationMin: 60,
});
eq(secondNight.days.map((d) => d.items.length), [1, 1], "the first copy stays where it was");
eq(keyOf(secondNight.days[1].items[0]) !== p1Key, true, "the copy gets its own id");
eq(placedDays(secondNight).get("p1"), [0, 1], "the badge names every day it is on");
const sameDay = planReducer(withBlock, {
  type: "add",
  place: place("p1", "Mentioned twice", 2),
  day: 0,
  startMin: 12 * 60,
  durationMin: 60,
});
eq(sameDay.days[0].items.length, 2, "the same place may sit twice on one day");
eq(placedDays(sameDay).get("p1"), [0], "and the badge names that day once");
const unpinned = planReducer(secondNight, {
  type: "remove",
  day: 1,
  key: keyOf(secondNight.days[1].items[0]),
});
eq(keyOf(unpinned.days[0].items[0]), p1Key, "removing one copy leaves the other");

const checked = (state: typeof base) =>
  planReducer(state, {
    type: "checked",
    route: { day_index: 0, date: itinerary.days[0].date, start_time: null, blocks: [],
             warnings: [], provisional: [] },
  });
const withBlockChecked = checked(withBlock);
eq(withBlockChecked.stale, [], "a checked day is no longer stale");
const linked = planReducer(withBlockChecked, {
  type: "reference",
  day: 0,
  key: p1Key,
  url: "https://airbnb.com/rooms/1",
});
eq(linked.days[0].items[0].reference_url, "https://airbnb.com/rooms/1", "the link is stored");
eq(linked.unsaved, [0], "a link marks the day unsaved");
eq(linked.stale, [], "a link does not re-route the day");
eq(
  planReducer(linked, { type: "reference", day: 0, key: p1Key, url: "https://airbnb.com/rooms/1" })
    .revision,
  linked.revision,
  "re-saving the same link changes nothing",
);
eq(
  planReducer(linked, { type: "reference", day: 0, key: p1Key, url: null }).days[0].items[0]
    .reference_url,
  null,
  "clearing the link removes it",
);

const stale = planReducer(withBlock, { type: "saved", days: [0], itinerary, revision: 0 });
eq(stale.unsaved, [0], "a save for an older revision is ignored");
const fresh = planReducer(withBlock, { type: "saved", days: [0], itinerary, revision: 1 });
eq(fresh.unsaved, [], "a save for the current revision clears the day");

const draft = { title: "Hotel Bristol", description: "Kristian IVs gate 7" };
let twice = planReducer(base, { type: "addCustom", day: 0, item: customItem(draft, 21 * 60, 120) });
twice = planReducer(twice, { type: "addCustom", day: 0, item: customItem(draft, 8 * 60, 60) });
const [early, late] = twice.days[0].items;
eq(twice.days[0].items.length, 2, "both blocks are kept");
eq(early.start_min < late.start_min, true, "and are in time order");
eq(keyOf(early) !== keyOf(late), true, "each gets its own id");
eq([early.place_id, early.kind], [null, "custom"], "a custom block claims no place");

const renamed = planReducer(checked(twice), {
  type: "editCustom",
  day: 0,
  key: keyOf(late),
  draft: { title: "Hotel Bristol · night 2", description: null },
});
eq(renamed.days[0].items.map((i) => i.name), ["Hotel Bristol", "Hotel Bristol · night 2"],
   "editing one leaves its twin alone");
eq(renamed.stale, [], "a rename does not re-route the day");

const removed = planReducer(twice, { type: "remove", day: 0, key: keyOf(early) });
eq(removed.days[0].items.map((i) => keyOf(i)), [keyOf(late)], "removing one leaves its twin");

eq(placedDays(twice).size, 0, "a custom block claims no shortlist row");

const placedIn = planReducer(base, { type: "city", day: 1, cityId: "oslo" });
eq(placedIn.days.map((d) => d.city_id ?? null), [null, "oslo"], "only that day moves city");
eq([placedIn.unsaved, placedIn.stale], [[1], base.stale], "a city is written, never re-routed");

console.log("plan-state: all checks passed");
