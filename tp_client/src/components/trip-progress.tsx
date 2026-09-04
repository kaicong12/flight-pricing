"use client";

// Polls one trip and renders the ingestion checklist, one row per (kind, status). The polled body
// is the only source of ingest status, so nothing on the page can go stale against it.

import Link from "next/link";
import { useEffect, useState } from "react";

import { FAILURE_TEXT, TERMINAL_STATUSES, type TripStatus } from "@/lib/api-types";

const POLL_MS = 3000;
const MAX_POLL_MS = 5 * 60 * 1000;

const STATUS_TEXT: Record<string, string> = {
  pending: "Queued",
  running: "Reading videos and posts",
  done: "Shortlist ready",
  failed: "Ingestion failed",
  needs_credentials: "Needs credentials",
};

export function TripProgress({ initial }: { initial: TripStatus }) {
  const [status, setStatus] = useState<TripStatus>(initial);
  const [stopped, setStopped] = useState(
    !initial.ingest || TERMINAL_STATUSES.includes(initial.ingest.status),
  );

  useEffect(() => {
    if (stopped) return;
    let live = true;
    const startedAt = Date.now();

    const timer = setInterval(async () => {
      if (Date.now() - startedAt > MAX_POLL_MS) {
        if (live) setStopped(true);
        return;
      }
      const r = await fetch(`/api/trips/${initial.trip_id}`);
      if (!r.ok || !live) return;
      const body = (await r.json()) as TripStatus;
      setStatus(body);
      if (body.ingest && TERMINAL_STATUSES.includes(body.ingest.status)) setStopped(true);
    }, POLL_MS);

    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [initial.trip_id, stopped]);

  const ingest = status.ingest;
  const state = ingest?.status ?? "done";
  const done = state === "done";
  const broken = state === "failed" || state === "needs_credentials";

  return (
    <section className="mt-8 rounded-card border border-border surface shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-6 py-4.5">
        <div className="flex items-center gap-2.5">
          {!done && !broken && (
            <span className="size-1.5 animate-[tp-pulse_1.4s_ease-in-out_infinite] motion-reduce:animate-none rounded-full bg-brand" />
          )}
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
            {STATUS_TEXT[state] ?? state}
          </h2>
        </div>
        <p className="font-mono text-[11px] text-faint">
          {ingest ? `run ${ingest.run_id.slice(0, 8)} · ${state}` : "no ingestion (city already warm)"}
        </p>
      </div>

      <div className="px-6 py-2">
        {status.progress.length === 0 ? (
          <p className="py-4 text-[13.5px] text-muted-foreground">
            {ingest ? "Queueing the first tasks…" : "This city was already ingested."}
          </p>
        ) : (
          status.progress.map((p) => (
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
          ))
        )}
      </div>

      {status.failures.length > 0 && <Failures failures={status.failures} />}

      {done ? (
        <Link
          href={`/trip/${initial.trip_id}/plan`}
          className="flex items-center justify-between gap-4 border-t border-border px-6 py-4 transition-colors hover:bg-page outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="text-[14px] font-semibold tracking-[-0.01em]">
            Build the itinerary →
          </span>
          <span className="font-mono text-[11px] text-faint">
            shortlist · order · route
          </span>
        </Link>
      ) : (
        <p className="border-t border-border px-6 py-3 font-mono text-[11px] text-faint">
          {state} · {stopped ? "polling stopped" : "polling"}
        </p>
      )}
    </section>
  );
}

function Failures({ failures }: { failures: TripStatus["failures"] }) {
  const total = failures.reduce((n, f) => n + f.count, 0);

  return (
    <details className="border-t border-border px-6 py-3">
      <summary className="cursor-pointer text-[13px] text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        {total} source{total === 1 ? "" : "s"} could not be read
      </summary>
      <ul className="mt-2.5 space-y-2">
        {failures.map((f) => (
          <li key={`${f.kind}:${f.status}:${f.last_error}`} className="flex gap-2.5">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-destructive/60" />
            <div className="min-w-0">
              <p className="font-mono text-[11px] text-faint">
                {f.kind}
                {f.count > 1 && ` · ${f.count}×`}
                {f.error_code && ` · ${f.error_code}`}
                {f.status === "blocked" && " · blocked"}
              </p>
              <p className="text-[12.5px] text-muted-foreground">
                {(f.error_code && FAILURE_TEXT[f.error_code]) ??
                  (f.status === "blocked" ? "Parked — nothing is registered to run it" : "Failed")}
              </p>
              {f.last_error && (
                <p className="mt-0.5 break-words font-mono text-[11px] text-faint">{f.last_error}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** `blocked` is terminal — no retry will ever pick it up — so it must not read as still waiting. */
function StageIcon({ status }: { status: string }) {
  if (status === "done")
    return (
      <span className="grid size-4.5 place-items-center rounded-full bg-ok text-[10px] font-bold text-primary-foreground">
        ✓
      </span>
    );
  if (status === "failed" || status === "blocked")
    return <span className="size-4 rounded-full border-2 border-destructive" />;
  if (status === "running")
    return (
      <span className="size-4 animate-[tp-spin_0.9s_linear_infinite] rounded-full border-2 border-[#dcd5c2] border-t-brand motion-reduce:animate-none" />
    );
  return <span className="size-4 rounded-full border-[1.5px] border-dashed border-[#d7cfba]" />;
}
