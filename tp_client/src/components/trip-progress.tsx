"use client";

// Wiring proof, not a designed screen: polls the trip and lists whatever the task checklist says.

import { useEffect, useState } from "react";

import { TERMINAL_STATUSES, type TripStatus } from "@/lib/api-types";

const POLL_MS = 3000;
const MAX_POLL_MS = 5 * 60 * 1000;

export function TripProgress({
  tripId,
  initialStatus,
}: {
  tripId: string;
  initialStatus: string;
}) {
  const [status, setStatus] = useState<TripStatus | null>(null);
  const [stopped, setStopped] = useState(TERMINAL_STATUSES.includes(initialStatus));

  useEffect(() => {
    if (stopped) return;
    let live = true;
    const startedAt = Date.now();

    const timer = setInterval(async () => {
      if (Date.now() - startedAt > MAX_POLL_MS) {
        if (live) setStopped(true);
        return;
      }
      const r = await fetch(`/api/trips/${tripId}`);
      if (!r.ok || !live) return;
      const body = (await r.json()) as TripStatus;
      setStatus(body);
      if (body.ingest && TERMINAL_STATUSES.includes(body.ingest.status)) setStopped(true);
    }, POLL_MS);

    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [tripId, stopped]);

  return (
    <div className="space-y-1 border-t border-input pt-3 font-mono text-xs">
      <p>
        status: {status?.ingest?.status ?? initialStatus}
        {stopped ? " (polling stopped)" : " (polling)"}
      </p>
      {(status?.progress ?? []).map((p) => (
        <p key={`${p.kind}:${p.status}`}>
          {p.kind} — {p.status} — {p.count}
        </p>
      ))}
    </div>
  );
}
