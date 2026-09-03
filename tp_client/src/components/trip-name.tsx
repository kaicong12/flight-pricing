"use client";

// Click-to-edit trip name, used by both the dashboard card and the plan header. Optimistic: the
// name is display-only, so showing it immediately and rolling back on failure beats a spinner.

import { Pencil } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

const NAME_MAX = 120;

export function TripName({
  tripId,
  name,
  fallback,
  className,
  onRenamed,
}: {
  tripId: string;
  name: string | null;
  fallback: string;
  className?: string;
  onRenamed?: (name: string | null) => void;
}) {
  // An override rather than a mirror of `name`: nothing to keep in sync, so no effect is needed.
  const [pending, setPending] = useState<string | null | undefined>(undefined);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const current = pending !== undefined ? pending : name;

  function open(e: React.MouseEvent) {
    // The card is a Link, so editing must not navigate.
    e.preventDefault();
    e.stopPropagation();
    setDraft(current ?? "");
    setEditing(true);
  }

  async function commit() {
    setEditing(false);
    const next = draft.trim() || null;
    if (next === current) return;

    const previous = current;
    setPending(next);
    onRenamed?.(next);

    const r = await fetch(`/api/trips/${tripId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: next }),
    });
    if (!r.ok) {
      setPending(previous);
      onRenamed?.(previous);
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        maxLength={NAME_MAX}
        aria-label="Trip name"
        placeholder={fallback}
        onFocus={(e) => e.target.select()}
        onChange={(e) => setDraft(e.target.value)}
        onClick={(e) => e.preventDefault()}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setEditing(false);
        }}
        className={cn(
          "w-full min-w-0 rounded-md border border-border bg-surface px-1.5 py-0.5 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          className,
        )}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={open}
      title="Rename this trip"
      className={cn(
        "group/name flex min-w-0 items-center gap-1.5 rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        className,
      )}
    >
      <span className="truncate">{current?.trim() || fallback}</span>
      <Pencil className="size-3.5 shrink-0 text-faint opacity-0 transition-opacity group-hover/name:opacity-100 group-focus-visible/name:opacity-100" />
    </button>
  );
}
