"use client";

// Polls the trip and renders whatever the task checklist says, one row per (kind, status).

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
    <div className="border-t border-hairline pt-3">
      {(status?.progress ?? []).map((p) => (
        <div
          key={`${p.kind}:${p.status}`}
          className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-3.5 border-b border-hairline py-2.5 last:border-b-0"
        >
          <StageIcon status={p.status} />
          <div>
            <p className="font-mono text-xs text-ink">{p.kind}</p>
            <p className="mt-0.5 font-mono text-[11px] text-faint">{p.status}</p>
          </div>
          <span className="font-mono text-[11.5px] text-muted-foreground">{p.count}</span>
        </div>
      ))}
      <p className="pt-3 font-mono text-[11px] text-faint">
        {status?.ingest?.status ?? initialStatus} · {stopped ? "polling stopped" : "polling"}
      </p>
    </div>
  );
}

/** A throttle wait is not a failure, so `blocked` renders as waiting rather than as an error. */
function StageIcon({ status }: { status: string }) {
  if (status === "done")
    return (
      <span className="grid size-4.5 place-items-center rounded-full bg-ok text-[10px] font-bold text-primary-foreground">
        ✓
      </span>
    );
  if (status === "failed") return <span className="size-4 rounded-full border-2 border-destructive" />;
  if (status === "running")
    return (
      <span className="size-4 animate-[tp-spin_0.9s_linear_infinite] rounded-full border-2 border-[#dcd5c2] border-t-brand motion-reduce:animate-none" />
    );
  return <span className="size-4 rounded-full border-[1.5px] border-dashed border-[#d7cfba]" />;
}
