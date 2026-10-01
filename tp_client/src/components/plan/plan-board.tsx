"use client";

// The planning screen's one stateful component. Everything mutable lives in the reducer here; the
// three columns are given props and raise events.
//
// Two debounces hang off it: the ordering is written back quickly, and the day is re-checked more
// slowly, because a write is local and the check re-reads opening hours.

import {
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  pointerWithin,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { restrictToWindowEdges } from "@dnd-kit/modifiers";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";

import type { Trip } from "@/lib/api-types";
import { type ExpenseTab, blockCost, costsByBlock } from "@/lib/expense-types";
import {
  type PlanState,
  dayOf,
  initialState,
  placedDays,
  planReducer,
} from "@/lib/plan-state";
import type {
  DayRoute,
  Itinerary,
  ItineraryItem,
  Shortlist,
  ShortlistPlace,
  ShortlistSource,
} from "@/lib/plan-types";
import {
  DEFAULT_DURATION,
  MIN_DURATION,
  SLOT_MIN,
  availableWindow,
  keyOf,
  piecesOn,
} from "@/lib/plan-types";

import { DayColumn } from "./day-column";
import { DayMap } from "./day-map";
import { DayTabs } from "./day-tabs";
import { PlanHeader } from "./plan-header";
import { ShortlistPanel } from "./shortlist-panel";

const SAVE_MS = 400;
const ROUTE_MS = 1200;
const PAGE = 40;

export function PlanBoard({
  trip,
  center,
  initialItinerary,
  initialShortlist,
  initialExpenses,
  meId,
  canEdit,
}: {
  trip: Trip;
  center: { lat: number; lon: number } | null;
  initialItinerary: Itinerary;
  initialShortlist: Shortlist;
  initialExpenses: ExpenseTab | null;
  meId: string;
  canEdit: boolean;
}) {
  const [state, dispatch] = useReducer(
    planReducer,
    undefined,
    () => initialState(initialItinerary, initialShortlist) satisfies PlanState,
  );
  const [category, setCategory] = useState<string | null>(null);
  const [source, setSource] = useState<ShortlistSource | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [routingDay, setRoutingDay] = useState<number | null>(null);
  // Stamped with the request that produced it, so "loading" is derived instead of set in an effect.
  const [loaded, setLoaded] = useState({
    category: null as string | null,
    source: null as ShortlistSource | null,
  });
  // The costs tab, so a block can show what it cost and the "$" can add one.
  const [expenses, setExpenses] = useState(initialExpenses);

  const reloadExpenses = useCallback(async () => {
    const r = await fetch(`/api/trips/${trip.trip_id}/expenses`);
    if (r.ok) setExpenses((await r.json()) as ExpenseTab);
  }, [trip.trip_id]);

  const costs = useMemo(() => {
    const out = new Map<string, string>();
    for (const [key, list] of costsByBlock(expenses?.expenses ?? [])) {
      out.set(key, blockCost(list));
    }
    return out;
  }, [expenses]);

  // One figure typed on a block: split evenly between everyone, paid by whoever typed it. Clearing
  // drops every cost on that block, which is what the "$" showing a total means.
  const saveCost = useCallback(
    async (item: ItineraryItem, amountCents: number | null, currency: string) => {
      const tab = expenses;
      if (!tab) return;
      const base = `/api/trips/${trip.trip_id}/expenses`;
      const existing = tab.expenses.filter(
        (e) => (e.place_id ?? e.block_id) === (item.place_id ?? item.block_id),
      );
      if (amountCents === null) {
        await Promise.all(
          existing.map((e) => fetch(`${base}/${e.expense_id}`, { method: "DELETE" })),
        );
      } else {
        const ids = tab.members.map((m) => m.user_id);
        await fetch(base, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            description: item.name,
            amount_cents: amountCents,
            currency,
            spent_on: dayDate(state, item),
            payer_id: meId,
            place_id: item.place_id,
            block_id: item.block_id,
            participants: ids,
          }),
        });
      }
      await reloadExpenses();
    },
    [expenses, meId, reloadExpenses, state, trip.trip_id],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const day = state.days.find((d) => d.day_index === state.activeDay) ?? state.days[0];
  const route = state.routes[state.activeDay];
  const isStale = state.stale.includes(state.activeDay);
  // A block drawn on this day may live on an earlier one, if it runs past midnight.
  const homeOf = (key: string) => dayOf(state, key) ?? state.activeDay;
  const placed = useMemo(() => placedDays(state), [state]);
  const provisional = useMemo(
    () => Object.values(state.routes).find((r) => r.provisional.length > 0)?.provisional ?? [],
    [state.routes],
  );

  // Write the ordering back. Only the days that actually changed are sent. Keyed on the revision
  // rather than on which days are dirty, so a second edit to the same day re-arms the timer with
  // fresh contents instead of letting the first one fire with a stale closure.
  const revision = state.revision;
  useEffect(() => {
    if (state.savedRevision === revision || !state.unsaved.length) return;
    const days = [...state.unsaved];
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      const payload = {
        days: days.map((index) => ({
          day_index: index,
          items: (state.days.find((d) => d.day_index === index)?.items ?? []).map((i) => ({
            kind: i.kind,
            place_id: i.place_id,
            block_id: i.block_id,
            title: i.kind === "custom" ? i.name : null,
            description: i.description,
            start_min: i.start_min,
            duration_min: i.duration_min,
            reference_url: i.reference_url,
          })),
        })),
      };
      try {
        const r = await fetch(`/api/trips/${trip.trip_id}/itinerary`, {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        if (r.ok) {
          dispatch({ type: "saved", days, itinerary: await r.json(), revision });
        }
      } catch {
        // Abandoned because another edit landed; that edit owns the write.
      }
    }, SAVE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision, state.savedRevision, trip.trip_id]);

  // Check the visible day once its edits settle. "Re-check day" re-marks it stale, which is the
  // same signal an edit produces, so there is one path in.
  // The check reads the day back from the database, so it must not run until the write has landed.
  const activeDay = state.activeDay;
  const needsRoute =
    isStale && day && day.items.length > 0 && state.savedRevision === state.revision;
  useEffect(() => {
    if (!needsRoute) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setRoutingDay(activeDay);
      try {
        const r = await fetch(`/api/trips/${trip.trip_id}/route-day?day=${activeDay}`, {
          method: "POST",
          signal: controller.signal,
        });
        if (r.ok) dispatch({ type: "checked", route: (await r.json()) as DayRoute });
        else dispatch({ type: "routeFailed", day: activeDay });
      } catch {
        // Superseded or navigated away. Leave the day stale so it retries.
      } finally {
        setRoutingDay(null);
      }
    }, ROUTE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [needsRoute, activeDay, trip.trip_id]);

  // Shortlist paging, category and source filtering.
  const settled = loaded.category === category && loaded.source === source;
  useEffect(() => {
    if (settled) return;
    const controller = new AbortController();
    (async () => {
      const query = new URLSearchParams({ limit: String(PAGE) });
      if (category) query.set("category", category);
      if (source) query.set("source", source);
      try {
        const r = await fetch(`/api/trips/${trip.trip_id}/shortlist?${query}`, {
          signal: controller.signal,
        });
        if (r.ok) {
          dispatch({ type: "shortlistLoaded", shortlist: await r.json(), append: false });
          setLoaded({ category, source });
        }
      } catch {
        // Superseded by another filter.
      }
    })();
    return () => controller.abort();
  }, [settled, category, source, trip.trip_id]);

  const loadMore = useCallback(async () => {
    const offset = state.shortlist.length;
    const query = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (category) query.set("category", category);
    if (source) query.set("source", source);
    const r = await fetch(`/api/trips/${trip.trip_id}/shortlist?${query}`);
    if (r.ok) dispatch({ type: "shortlistLoaded", shortlist: await r.json(), append: true });
  }, [category, source, state.shortlist.length, trip.trip_id]);

  const dismiss = useCallback(
    async (place: ShortlistPlace) => {
      dispatch({ type: "dismiss", placeId: place.place_id });
      await fetch(`/api/trips/${trip.trip_id}/dismissals`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ place_id: place.place_id }),
      });
    },
    [trip.trip_id],
  );

  // Not optimistic, unlike dismiss: the server owns the name and coordinates. Resolves to an error.
  const addPlace = useCallback(
    async (placeId: string, category: string): Promise<string | null> => {
      let r: Response;
      try {
        r = await fetch(`/api/trips/${trip.trip_id}/places`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ place_id: placeId, category }),
        });
      } catch {
        return "Could not reach the planner.";
      }
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        return typeof body?.detail === "string" ? body.detail : "That place could not be added.";
      }
      dispatch({ type: "placeAdded", place: (await r.json()) as ShortlistPlace });
      return null;
    },
    [trip.trip_id],
  );

  function onDragStart(event: DragStartEvent) {
    setDragging(String(event.active.id));
  }

  function onDragEnd(event: DragEndEvent) {
    setDragging(null);
    const { active, over } = event;
    if (!over) return;

    const activeId = String(active.id);
    const overData = over.data.current as
      | { kind?: string; day?: number; minute?: number }
      | undefined;
    // A half-hour slot is the only thing that takes a drop, and only the active day draws any, so
    // every drop names both a time and the day already on screen.
    if (overData?.kind !== "slot" || overData.day === undefined || overData.minute === undefined) {
      return;
    }

    const targetDay = overData.day;
    const slotMin = overData.minute;

    if (activeId.startsWith("shortlist:")) {
      const place = (active.data.current as { place: ShortlistPlace }).place;
      const room = availableWindow(trip, targetDay, state.days.length).to - slotMin;
      dispatch({
        type: "add",
        place,
        day: targetDay,
        startMin: slotMin,
        // A new block gets an hour unless the flight leaves less than that.
        durationMin: Math.max(
          MIN_DURATION,
          Math.min(DEFAULT_DURATION, Math.floor(room / SLOT_MIN) * SLOT_MIN),
        ),
      });
      return;
    }

    const key = activeId.slice("item:".length);
    const fromDay = dayOf(state, key);
    if (fromDay === null) return;

    // toDay is the block's own day, never the drop's: dragging changes when, never which day.
    dispatch({ type: "pin", key, fromDay, toDay: fromDay, startMin: slotMin });
  }

  if (!day) return null;

  return (
    <DndContext
      // Fixed, because dnd-kit otherwise derives its aria-describedby ids from a render counter and
      // the server and client land on different numbers.
      id="plan-board"
      sensors={sensors}
      collisionDetection={collisionDetection}
      modifiers={[restrictToWindowEdges]}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragging(null)}
    >
      <PlanHeader
        trip={trip}
        days={state.days}
        placeCount={state.total}
        provisional={provisional}
        meId={meId}
        canEdit={canEdit}
        stale={isStale}
        routing={routingDay !== null}
        onReroute={() => dispatch({ type: "invalidate", day: state.activeDay })}
      />

      <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)_minmax(0,1fr)]">
        <ShortlistPanel
          places={state.shortlist}
          total={state.total}
          placedDays={placed}
          category={category}
          loading={!settled}
          tripId={trip.trip_id}
          onCategory={setCategory}
          source={source}
          onSource={setSource}
          readOnly={!canEdit}
          onDismiss={dismiss}
          onAdd={addPlace}
          onMore={loadMore}
        />

        <section className="overflow-hidden rounded-card border border-border surface shadow-card">
          <DayTabs
            days={state.days}
            activeDay={state.activeDay}
            onSelect={(d) => dispatch({ type: "activeDay", day: d })}
          />
          <DayColumn
            day={day}
            days={state.days}
            windowOf={(d) => availableWindow(trip, d, state.days.length)}
            route={route}
            stale={isStale}
            readOnly={!canEdit}
            available={availableWindow(trip, state.activeDay, state.days.length)}
            costs={costs}
            currency={expenses?.currency ?? "EUR"}
            onCost={saveCost}
            onRemove={(key) => dispatch({ type: "remove", day: homeOf(key), key })}
            onReference={(key, url) => dispatch({ type: "reference", day: homeOf(key), key, url })}
            onAddCustom={(startMin, draft, durationMin) =>
              dispatch({ type: "addCustom", day: state.activeDay, startMin, durationMin, draft })
            }
            onEditCustom={(key, draft) =>
              dispatch({ type: "editCustom", day: homeOf(key), key, draft })
            }
            onResize={(key, startMin, durationMin) => {
              // A top-edge drag changes both, so both go through, each guarded against a no-op.
              const home = homeOf(key);
              dispatch({ type: "pin", key, fromDay: home, toDay: home, startMin });
              dispatch({ type: "duration", day: home, key, minutes: durationMin });
            }}
          />
        </section>

        <DayMap
          day={{ ...day, items: piecesOn(state.days, day.day_index).map((p) => p.item) }}
          centerLat={center?.lat ?? null}
          centerLon={center?.lon ?? null}
        />
      </div>

      <DragOverlay dropAnimation={null}>
        {dragging && (
          <div className="rounded-full border border-ink bg-surface px-3.5 py-1.5 text-[13px] font-medium shadow-lift">
            {labelFor(state, dragging)}
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}

/**
 * Cursor first: closestCenter alone resolves a drop from the drag overlay's centre, which sits
 * wherever the pointer grabbed the row, so aiming at one half hour lands on the next. closestCenter
 * stays as the fallback for a pointer outside every slot, e.g. over a day tab.
 */
const collisionDetection: typeof pointerWithin = (args) => {
  const hit = pointerWithin(args);
  if (hit.length > 0) return hit;

  // A blocked hour is not a droppable, so closestCenter is what keeps a drop on the hatched part of
  // the grid forgiving. Off the grid altogether — a day tab, say — that same fallback would snap to
  // whichever slot happened to be nearest and silently retime the block, so a stray drag has to
  // mean nothing instead. A keyboard drag has no pointer and keeps the fallback.
  const pointer = args.pointerCoordinates;
  if (!pointer) return closestCenter(args);
  const grid = document.querySelector("[data-grid]")?.getBoundingClientRect();
  const onGrid =
    grid !== undefined &&
    pointer.x >= grid.left &&
    pointer.x <= grid.right &&
    pointer.y >= grid.top &&
    pointer.y <= grid.bottom;
  return onGrid ? closestCenter(args) : [];
};

/** The date of the day a block sits on, which is when its cost was spent. */
function dayDate(state: PlanState, item: ItineraryItem): string {
  const key = keyOf(item);
  for (const d of state.days) {
    if (d.items.some((i) => keyOf(i) === key)) return d.date;
  }
  return state.days[0].date;
}

function labelFor(state: PlanState, dragId: string): string {
  if (dragId.startsWith("shortlist:")) {
    const id = dragId.slice("shortlist:".length);
    return state.shortlist.find((p) => p.place_id === id)?.name ?? "Place";
  }
  const id = dragId.slice("item:".length);
  for (const d of state.days) {
    const found = d.items.find((i) => keyOf(i) === id);
    if (found) return found.name;
  }
  return "Place";
}
