"use client";

// THROWAWAY SPIKE: /spike/calendar. Does drag-to-a-time-slot with edge resizing actually feel
// right? Nothing here is wired to tp_api — no fetch, no save, no routing. Fixture data only.
//
// Reuses the plan board's dnd-kit setup and its `prefix:id` + `{ kind }` data convention, but not
// SortableContext: a grid is positioned, not a flow list. Each half hour is its own droppable, so a
// drop reports a time directly instead of pixel maths.

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { restrictToWindowEdges } from "@dnd-kit/modifiers";
import { useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { BY_ID, CANDIDATES, DAY_END, DAY_LABEL, DAY_START, SUNSET, travelMin } from "./fixture";
import {
  DEFAULT_DURATION,
  MIN_DURATION,
  SLOT_MIN,
  type Conflict,
  type Stop,
  conflicts,
  endOf,
  heightPx,
  hhmm,
  layout,
  resize,
  slotAt,
  topPx,
} from "./slots";

const SLOT_PX = 26;
const SLOTS = Math.round((DAY_END - DAY_START) / SLOT_MIN);

/**
 * Cursor first, and this matters at this scale: `closestCenter` alone resolves a drop from the drag
 * overlay's centre, which sits wherever the pointer happened to grab the row — so aiming at 16:00
 * reliably landed on 16:30. `closestCenter` stays as the fallback for when the pointer is outside
 * every slot, which is what keeps a drop near the edge of the grid from being swallowed.
 */
const collisionDetection: typeof pointerWithin = (args) => {
  const hit = pointerWithin(args);
  return hit.length > 0 ? hit : closestCenter(args);
};

const CONFLICT_TEXT: Record<Conflict["code"], (c: Conflict) => string> = {
  travel_does_not_fit: (c) =>
    c.code === "travel_does_not_fit"
      ? `${c.needMin} min walk from ${BY_ID.get(c.fromId)?.name ?? "the last stop"} does not fit${
          c.gapMin > 0 ? ` in ${c.gapMin} min` : ""
        }`
      : "",
  opens_later: (c) => (c.code === "opens_later" ? `Opens ${hhmm(c.opensAt)} — ${c.waitMin} min wait` : ""),
  closes_before_done: (c) => (c.code === "closes_before_done" ? `Closes ${hhmm(c.closesAt)}` : ""),
  after_sunset: (c) => (c.code === "after_sunset" ? `Dark — sunset ${hhmm(c.sunsetMin)}` : ""),
  outside_day: () => "Outside the day",
};

export default function CalendarSpike() {
  const [stops, setStops] = useState<Stop[]>([
    { id: "polar", name: "The Polar Museum", startMin: 600, durationMin: 90, openFrom: 600, openTo: 1080 },
    { id: "raketten", name: "Raketten Bar & Pølse", startMin: 690, durationMin: 60, openFrom: 720, openTo: 1140 },
    { id: "fjell", name: "Fjellheisen", startMin: 810, durationMin: 120, openFrom: 540, openTo: 1440, outdoor: true },
  ]);
  const [dragging, setDragging] = useState<string | null>(null);
  const grid = useRef<HTMLDivElement>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor),
  );

  const placed = useMemo(() => layout(stops), [stops]);
  const found = useMemo(
    () => conflicts(stops, travelMin, { dayStartMin: DAY_START, dayEndMin: DAY_END, sunsetMin: SUNSET }),
    [stops],
  );
  const byStop = useMemo(() => {
    const m = new Map<string, Conflict[]>();
    for (const c of found) m.set(c.id, [...(m.get(c.id) ?? []), c]);
    return m;
  }, [found]);

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setDragging(null);
    const startMin = (over?.data.current as { minute?: number } | undefined)?.minute;
    if (startMin == null) return;

    const id = String(active.id);
    if (id.startsWith("cand:")) {
      const cand = BY_ID.get(id.slice(5));
      if (!cand || stops.some((s) => s.id === cand.id)) return;
      setStops((prev) => [...prev, {
        id: cand.id, name: cand.name, startMin, durationMin: DEFAULT_DURATION,
        openFrom: cand.openFrom, openTo: cand.openTo, outdoor: cand.outdoor,
      }]);
      return;
    }
    const stopId = id.slice(5);
    setStops((prev) => prev.map((s) => (s.id === stopId ? { ...s, startMin } : s)));
  };

  /**
   * Resize on raw pointer events rather than dnd-kit: one commit on pointerup, because the real
   * board re-routes on every duration change and a continuous drag would spend a call per pixel.
   */
  const startResize = (stopId: string, edge: "top" | "bottom") => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const box = grid.current?.getBoundingClientRect();
    if (!box) return;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);

    const move = (ev: PointerEvent) => {
      const min = slotAt(ev.clientY - box.top, DAY_START, SLOT_PX);
      setStops((prev) => prev.map((s) => (s.id === stopId ? resize(s, edge, min) : s)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const draggingName = dragging?.startsWith("cand:")
    ? BY_ID.get(dragging.slice(5))?.name
    : stops.find((s) => s.id === dragging?.slice(5))?.name;

  return (
    <main className="mx-auto max-w-[1060px] px-7 py-8">
      <p className="font-mono text-[11px] text-faint">THROWAWAY SPIKE · /spike/calendar</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-[-0.015em]">Pin a place to a time</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Drag a place onto a half-hour slot. Drag a block&apos;s top or bottom edge to change how long
        you spend there, {MIN_DURATION} minutes minimum. Nothing is ever moved for you — the warnings
        say what does not work.
      </p>

      <DndContext
        // Fixed, like the real board: dnd-kit otherwise derives aria ids from a render counter and
        // SSR disagrees with the client.
        id="calendar-spike"
        sensors={sensors}
        collisionDetection={collisionDetection}
        modifiers={[restrictToWindowEdges]}
        onDragStart={({ active }: DragStartEvent) => setDragging(String(active.id))}
        onDragCancel={() => setDragging(null)}
        onDragEnd={onDragEnd}
      >
        <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
          <section className="overflow-hidden rounded-card border border-border surface shadow-card">
            <header className="border-b border-border px-5 py-4">
              <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Shortlist</h2>
              <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                Drag one onto the day at the time you want it.
              </p>
            </header>
            <ul className="max-h-[calc(100dvh-260px)] overflow-y-auto px-3 py-2">
              {CANDIDATES.map((c) => (
                <CandidateRow key={c.id} candidate={c} used={stops.some((s) => s.id === c.id)} />
              ))}
            </ul>
          </section>

          <section className="overflow-hidden rounded-card border border-border surface shadow-card">
            <header className="flex items-baseline justify-between border-b border-border px-5 py-4">
              <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{DAY_LABEL}</h2>
              <p className="font-mono text-[11px] text-faint">
                {stops.length} pinned · {found.length} warning{found.length === 1 ? "" : "s"} · sunset{" "}
                {hhmm(SUNSET)}
              </p>
            </header>

            <div className="max-h-[calc(100dvh-260px)] overflow-y-auto px-5 py-4">
              <div className="relative flex" style={{ height: SLOTS * SLOT_PX }}>
                <div className="w-12 shrink-0">
                  {Array.from({ length: SLOTS }, (_, i) => DAY_START + i * SLOT_MIN)
                    .filter((m) => m % 60 === 0)
                    .map((m) => (
                      <span
                        key={m}
                        className="absolute font-mono text-[11px] text-faint"
                        style={{ top: topPx(m, DAY_START, SLOT_PX) - 6 }}
                      >
                        {hhmm(m)}
                      </span>
                    ))}
                </div>

                <div ref={grid} className="relative flex-1">
                  {Array.from({ length: SLOTS }, (_, i) => (
                    <Slot key={i} minute={DAY_START + i * SLOT_MIN} />
                  ))}

                  {placed.map((p) => (
                    <Block
                      key={p.id}
                      placed={p}
                      conflicts={byStop.get(p.id) ?? []}
                      onResize={startResize}
                      onRemove={() => setStops((prev) => prev.filter((s) => s.id !== p.id))}
                    />
                  ))}
                </div>
              </div>
            </div>

            {found.length > 0 && (
              <ul className="border-t border-border px-5 py-3">
                {found.map((c, i) => (
                  <li key={i} className="flex gap-2 py-0.5 text-[12.5px] text-alert">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-alert" />
                    <span>
                      <span className="font-medium">{BY_ID.get(c.id)?.name}</span>{" "}
                      {CONFLICT_TEXT[c.code](c)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <DragOverlay dropAnimation={null}>
          {draggingName && (
            <span className="flex h-8 items-center rounded-full bg-ink px-3 text-[13px] font-medium text-primary-foreground shadow-lift">
              {draggingName}
            </span>
          )}
        </DragOverlay>
      </DndContext>
    </main>
  );
}

function CandidateRow({ candidate, used }: { candidate: (typeof CANDIDATES)[number]; used: boolean }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `cand:${candidate.id}`,
    data: { kind: "candidate", candidate },
    disabled: used,
  });

  return (
    <li
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      className={cn(
        "rounded-card-sm px-2.5 py-2.5 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        used ? "opacity-40" : "cursor-grab touch-none hover:bg-page",
        isDragging && "opacity-30",
      )}
    >
      <p className="text-[13.5px] font-medium text-ink">{candidate.name}</p>
      <p className="mt-0.5 font-mono text-[11px] text-faint">
        {candidate.category}
        {candidate.openFrom != null && candidate.openTo != null
          ? ` · ${hhmm(candidate.openFrom)}-${hhmm(candidate.openTo)}`
          : " · hours unknown"}
        {used && " · on the day"}
      </p>
    </li>
  );
}

/** One half hour. Being a droppable is what makes a drop report a time rather than a pixel. */
function Slot({ minute }: { minute: number }) {
  const { setNodeRef, isOver } = useDroppable({
    id: `slot:${minute}`,
    data: { kind: "slot", minute },
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "border-t",
        minute % 60 === 0 ? "border-border" : "border-hairline",
        isOver && "bg-brand-bg",
      )}
      style={{ height: SLOT_PX }}
    />
  );
}

function Block({
  placed,
  conflicts: found,
  onResize,
  onRemove,
}: {
  placed: ReturnType<typeof layout>[number];
  conflicts: Conflict[];
  onResize: (id: string, edge: "top" | "bottom") => (e: React.PointerEvent) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `stop:${placed.id}`,
    data: { kind: "stop", stop: placed },
  });

  const bad = found.length > 0;
  const width = `calc(${100 / placed.lanes}% - 4px)`;

  return (
    <div
      className="absolute"
      style={{
        top: topPx(placed.startMin, DAY_START, SLOT_PX),
        height: heightPx(placed.durationMin, SLOT_PX) - 2,
        left: `calc(${(placed.lane * 100) / placed.lanes}% + 2px)`,
        width,
      }}
    >
      <div
        className={cn(
          "group/block relative flex h-full flex-col overflow-hidden border px-2.5 py-1.5",
          bad ? "border-alert/40 bg-alert-bg" : "border-border bg-page",
          isDragging && "opacity-30",
        )}
      >
        <button
          type="button"
          aria-label={`Start ${placed.name} earlier or later`}
          onPointerDown={onResize(placed.id, "top")}
          className="absolute inset-x-0 top-0 h-2 cursor-ns-resize touch-none opacity-0 transition-opacity group-hover/block:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <span className="mx-auto block h-0.5 w-8 rounded-full bg-ink/25" />
        </button>

        <div
          ref={setNodeRef}
          {...attributes}
          {...listeners}
          className="min-h-0 flex-1 cursor-grab touch-none outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <p className="truncate text-[13px] font-medium text-ink">{placed.name}</p>
          <p className="font-mono text-[10.5px] text-faint">
            {hhmm(placed.startMin)}–{hhmm(endOf(placed))} · {placed.durationMin} min
          </p>
        </div>

        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${placed.name}`}
          className="absolute top-1 right-1 size-5 rounded-full text-faint opacity-0 transition-opacity group-hover/block:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          ×
        </button>

        <button
          type="button"
          aria-label={`Change how long you spend at ${placed.name}`}
          onPointerDown={onResize(placed.id, "bottom")}
          className="absolute inset-x-0 bottom-0 h-2 cursor-ns-resize touch-none opacity-0 transition-opacity group-hover/block:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <span className="mx-auto block h-0.5 w-8 rounded-full bg-ink/25" />
        </button>
      </div>
    </div>
  );
}
