"use client";

// The day's places on a map, numbered in the user's order. MapLibre with a keyless basemap: no
// Google key may reach client JS. No line is drawn between them — travel is not modelled.

import "maplibre-gl/dist/maplibre-gl.css";

// maplibre-gl 6 dropped its default export, so these are named.
import {
  LngLatBounds,
  type LngLatBoundsLike,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
} from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { DayRoute, ItineraryDay } from "@/lib/plan-types";

// A style URL, not a key — swappable without a deploy if the tile host goes away. OpenStreetMap
// attribution is carried by the style and rendered by MapLibre's own control; do not remove it.
const STYLE_URL =
  process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? "https://tiles.openfreemap.org/styles/positron";

const LAND = "#e8e7d6";
const WATER = "#bfd2de";
const INK = "#252b20";

/** Nudge the basemap toward the app's paper palette. Unknown layer ids are skipped, not fatal. */
function tint(map: MapLibreMap) {
  for (const layer of map.getStyle().layers ?? []) {
    const id = layer.id.toLowerCase();
    try {
      if (layer.type === "background") map.setPaintProperty(layer.id, "background-color", LAND);
      else if (id.includes("water") || id.includes("ocean") || id.includes("sea")) {
        if (layer.type === "fill") map.setPaintProperty(layer.id, "fill-color", WATER);
      } else if (id.includes("landcover") || id.includes("landuse") || id.includes("park")) {
        if (layer.type === "fill") map.setPaintProperty(layer.id, "fill-opacity", 0.35);
      }
    } catch {
      // A style that names its layers differently just renders untinted.
    }
  }
}

function marker(index: number, name: string): HTMLElement {
  const el = document.createElement("div");
  el.className = "flex items-center gap-1.5";
  el.innerHTML =
    `<span class="grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white shadow-card" style="background:${INK}">${index + 1}</span>` +
    `<span class="max-w-38 truncate rounded-full bg-white/92 px-2 py-0.5 text-[11.5px] font-medium" style="color:${INK}"></span>`;
  el.querySelector("span:last-child")!.textContent = name;
  return el;
}

// Centre arrives as two numbers rather than an object so a re-render with an equal-but-new object
// does not tear the map down and rebuild it.
export function DayMap({
  day,
  route,
  centerLat,
  centerLon,
  stale,
}: {
  day: ItineraryDay;
  route: DayRoute | undefined;
  centerLat: number | null;
  centerLon: number | null;
  stale: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  // Our own stops do not depend on the basemap, so they are gated on the style being parsed rather
  // than on `load`, which waits for every tile source. A tile host that never answers must not also
  // cost us the pins.
  const styleReady = useRef(false);
  const redraw = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!container.current || map.current) return;
    const m = new MapLibreMap({
      container: container.current,
      style: STYLE_URL,
      center: [centerLon ?? 0, centerLat ?? 0],
      zoom: centerLat === null ? 1 : 12,
      attributionControl: { compact: true },
    });
    m.addControl(new NavigationControl({ showCompass: false }), "top-right");
    m.on("style.load", () => {
      tint(m);
      styleReady.current = true;
      redraw.current?.();
    });
    // A tile host that goes down otherwise fails silently and looks like a bug in this component.
    m.on("error", (e) => console.error("map:", e?.error?.message ?? e));
    map.current = m;

    // The column is flexible, and MapLibre only learns its size when told.
    const observer = new ResizeObserver(() => m.resize());
    observer.observe(container.current);

    return () => {
      observer.disconnect();
      m.remove();
      map.current = null;
      styleReady.current = false;
    };
  }, [centerLat, centerLon]);

  // Markers, redrawn whenever the day changes.
  useEffect(() => {
    const m = map.current;
    if (!m) return;

    const draw = () => {
      markers.current.forEach((x) => x.remove());
      markers.current = [];

      const points: [number, number][] = [];
      day.items.forEach((item, index) => {
        if (item.lon === null || item.lat === null) return;
        points.push([item.lon, item.lat]);
        markers.current.push(
          new Marker({ element: marker(index, item.name), anchor: "left" })
            .setLngLat([item.lon, item.lat])
            .addTo(m),
        );
      });

      if (points.length > 1) {
        const bounds = points.reduce(
          (b, c) => b.extend(c),
          new LngLatBounds(points[0], points[0]),
        );
        m.fitBounds(bounds as LngLatBoundsLike, { padding: 64, maxZoom: 15, duration: 400 });
      } else if (points.length === 1) {
        m.easeTo({ center: points[0], zoom: 14, duration: 400 });
      }
    };

    redraw.current = draw;
    if (styleReady.current) draw();
  }, [day]);

  // z-31 lifts the card above the layout's z-30 grain: mix-blend-multiply over an accelerated WebGL
  // canvas makes Chromium composite it as blank, so the map forgoes the grain to let others keep it.
  // Both stay under the z-50 overlay layer, or the map paints over open dialogs.
  return (
    <div className="relative z-31 h-[calc(100dvh-140px)] min-h-[420px] overflow-hidden rounded-card border border-border bg-land shadow-card isolate">
      {/* Sized explicitly: maplibre-gl.css forces position:relative on its own container, which
          beats an `absolute inset-0` utility and silently collapses the map to zero height. */}
      <div ref={container} className="h-full w-full" />

      <div className="pointer-events-none absolute top-3.5 left-3.5 flex flex-wrap items-center gap-1.5">
        <span className="flex h-7 items-center rounded-full bg-white/92 px-3 text-[12.5px] font-medium text-ink shadow-card">
          Day {day.day_index + 1}
        </span>
      </div>

      {route?.daylight && !stale && (
        <span className="pointer-events-none absolute right-3.5 bottom-9 flex h-7 items-center rounded-full bg-white/92 px-3 text-[12.5px] text-ink-soft shadow-card">
          Daylight {route.daylight.sunrise} – {route.daylight.sunset}
        </span>
      )}
    </div>
  );
}
