"use client";

// The planning screen's one stateful component. Everything mutable lives in the reducer here; the
// three columns are given props and raise events.
//
// Two debounces hang off it: the ordering is written back quickly, and the day is re-routed more
// slowly, because a write is free and a Routes call is not.

import {
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { restrictToWindowEdges } from "@dnd-kit/modifiers";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";

import type { Trip } from "@/lib/api-types";
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
  Shortlist,
  ShortlistPlace,
  TravelMode,
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
}: {
  trip: Trip;
  center: { lat: number; lon: number } | null;
  initialItinerary: Itinerary;
  initialShortlist: Shortlist;
}) {
  const [state, dispatch] = useReducer(
    planReducer,
    undefined,
    () => initialState(initialItinerary, initialShortlist, "walk") satisfies PlanState,
  );
  const [category, setCategory] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [routingDay, setRoutingDay] = useState<number | null>(null);
  // Stamped with the request that produced it, so "loading" is derived instead of set in an effect.
  const [loaded, setLoaded] = useState({ category: null as string | null });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const day = state.days.find((d) => d.day_index === state.activeDay) ?? state.days[0];
  const route = state.routes[state.activeDay];
  const isStale = state.stale.includes(state.activeDay);
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
            place_id: i.place_id,
            duration_min: i.duration_min,
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

  // Route the visible day once its edits settle. "Re-route day" re-marks it stale, which is the
  // same signal an edit produces, so there is one path in.
  // Routing reads the day back from the database, so it must not run until the write has landed.
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
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ mode: state.mode }),
          signal: controller.signal,
        });
        if (r.ok) dispatch({ type: "routed", route: (await r.json()) as DayRoute });
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
  }, [needsRoute, activeDay, state.mode, trip.trip_id]);

  // Shortlist paging and category filtering.
  const settled = loaded.category === category;
  useEffect(() => {
    if (settled) return;
    const controller = new AbortController();
    (async () => {
      const query = new URLSearchParams({ limit: String(PAGE) });
      if (category) query.set("category", category);
      try {
        const r = await fetch(`/api/trips/${trip.trip_id}/shortlist?${query}`, {
          signal: controller.signal,
        });
        if (r.ok) {
          dispatch({ type: "shortlistLoaded", shortlist: await r.json(), append: false });
          setLoaded({ category });
        }
      } catch {
        // Superseded by another filter.
      }
    })();
    return () => controller.abort();
  }, [settled, category, trip.trip_id]);

  const loadMore = useCallback(async () => {
    const offset = state.shortlist.length;
    const query = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (category) query.set("category", category);
    const r = await fetch(`/api/trips/${trip.trip_id}/shortlist?${query}`);
    if (r.ok) dispatch({ type: "shortlistLoaded", shortlist: await r.json(), append: true });
  }, [category, state.shortlist.length, trip.trip_id]);

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

  function onDragStart(event: DragStartEvent) {
    setDragging(String(event.active.id));
  }

  function onDragEnd(event: DragEndEvent) {
    setDragging(null);
    const { active, over } = event;
    if (!over) return;

    const activeId = String(active.id);
    const overId = String(over.id);
    const overData = over.data.current as { kind?: string; day?: number } | undefined;

    // Where did it land: an explicit day target, or beside another block?
    const targetDay =
      overData?.kind === "day" ? overData.day! : dayOfItemId(state, overId) ?? state.activeDay;

    if (activeId.startsWith("shortlist:")) {
      const place = (active.data.current as { place: ShortlistPlace }).place;
      dispatch({ type: "add", place, day: targetDay });
      if (targetDay !== state.activeDay) dispatch({ type: "activeDay", day: targetDay });
      return;
    }

    const placeId = activeId.slice("item:".length);
    const fromDay = dayOf(state, placeId);
    if (fromDay === null) return;

    if (targetDay !== fromDay) {
      const target = state.days.find((d) => d.day_index === targetDay);
      dispatch({
        type: "move",
        placeId,
        fromDay,
        toDay: targetDay,
        toIndex: target?.items.length ?? 0,
      });
      return;
    }

    const items = state.days.find((d) => d.day_index === fromDay)?.items ?? [];
    const from = items.findIndex((i) => i.place_id === placeId);
    const to = items.findIndex((i) => `item:${i.place_id}` === overId);
    if (from >= 0 && to >= 0 && from !== to) {
      dispatch({ type: "reorder", day: fromDay, from, to });
    }
  }

  if (!day) return null;

  return (
    <DndContext
      // Fixed, because dnd-kit otherwise derives its aria-describedby ids from a render counter and
      // the server and client land on different numbers.
      id="plan-board"
      sensors={sensors}
      collisionDetection={closestCenter}
      modifiers={[restrictToWindowEdges]}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragging(null)}
    >
      <PlanHeader
        trip={trip}
        placeCount={state.total}
        provisional={provisional}
        mode={state.mode}
        stale={isStale}
        routing={routingDay !== null}
        onMode={(mode: TravelMode) => dispatch({ type: "mode", mode })}
        onReroute={() => dispatch({ type: "invalidate", day: state.activeDay })}
      />

      <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)_minmax(0,1fr)]">
        <ShortlistPanel
          places={state.shortlist}
          total={state.total}
          placedDays={placed}
          category={category}
          loading={!settled}
          onCategory={setCategory}
          onAdd={(place) => dispatch({ type: "add", place, day: state.activeDay })}
          onDismiss={dismiss}
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
            route={route}
            mode={state.mode}
            stale={isStale}
            onRemove={(placeId) =>
              dispatch({ type: "remove", day: state.activeDay, placeId })
            }
            onDuration={(placeId, minutes) =>
              dispatch({ type: "duration", day: state.activeDay, placeId, minutes })
            }
          />
        </section>

        <DayMap
          day={day}
          route={route}
          centerLat={center?.lat ?? null}
          centerLon={center?.lon ?? null}
          stale={isStale}
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

function dayOfItemId(state: PlanState, overId: string): number | null {
  if (!overId.startsWith("item:")) return null;
  return dayOf(state, overId.slice("item:".length));
}

function labelFor(state: PlanState, dragId: string): string {
  if (dragId.startsWith("shortlist:")) {
    const id = dragId.slice("shortlist:".length);
    return state.shortlist.find((p) => p.place_id === id)?.name ?? "Place";
  }
  const id = dragId.slice("item:".length);
  for (const d of state.days) {
    const found = d.items.find((i) => i.place_id === id);
    if (found) return found.name;
  }
  return "Place";
}
