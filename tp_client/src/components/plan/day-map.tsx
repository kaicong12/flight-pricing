"use client";

// The day's places on a map, numbered in the user's order.

import "maplibre-gl/dist/maplibre-gl.css";

// maplibre-gl 6 has no default export.
import {
  LngLatBounds,
  type LngLatBoundsLike,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
} from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { ItineraryDay } from "@/lib/plan-types";

// OpenStreetMap attribution is rendered by the style's control; do not remove it.
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

// Two numbers, not an object: an equal-but-new object would rebuild the map.
export function DayMap({
  day,
  centerLat,
  centerLon,
}: {
  day: ItineraryDay;
  centerLat: number | null;
  centerLon: number | null;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  // Gated on the style parsing, not `load`, which waits on every tile source.
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
    m.on("error", (e) => console.error("map:", e?.error?.message ?? e));
    map.current = m;

    // MapLibre only learns its size when told.
    const observer = new ResizeObserver(() => m.resize());
    observer.observe(container.current);

    return () => {
      observer.disconnect();
      m.remove();
      map.current = null;
      styleReady.current = false;
    };
  }, [centerLat, centerLon]);

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

  // z-31 over the z-30 grain: Chromium blanks mix-blend-multiply over WebGL; under z-50 dialogs.
  return (
    <div className="relative z-31 h-[calc(100dvh-140px)] min-h-[420px] overflow-hidden rounded-card border border-border bg-land shadow-card isolate">
      {/* maplibre-gl.css forces position:relative on its container, so it is sized explicitly. */}
      <div ref={container} className="h-full w-full" />

      <div className="pointer-events-none absolute top-3.5 left-3.5 flex flex-wrap items-center gap-1.5">
        <span className="flex h-7 items-center rounded-full bg-white/92 px-3 text-[12.5px] font-medium text-ink shadow-card">
          Day {day.day_index + 1}
        </span>
      </div>
    </div>
  );
}
