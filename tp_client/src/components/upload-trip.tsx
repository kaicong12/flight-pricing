"use client";

// Upload new trip: a workbook exported from here, edited in Excel or not, becomes a new trip you
// own. The server refuses any other file, so this only previews what it read and creates it.

import { Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { type Trip, errorText } from "@/lib/api-types";
import { tripHref } from "@/lib/trips";
import { cn } from "@/lib/utils";

type Preview = {
  name: string | null;
  cities: string[];
  arrive_date: string;
  depart_date: string;
  days: { day_index: number; date: string; blocks: { kind: string; name: string; start: string; end: string }[] }[];
  skipped: { row: number; reason: string }[];
};

async function base64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

const DAY_MS = 86_400_000;

function shift(iso: string, days: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

export function UploadTrip({ look = "button" }: { look?: "button" | "link" }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex items-center gap-1.5 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          look === "button"
            ? "h-10 shrink-0 rounded-full border border-border px-4 text-[13.5px] font-medium whitespace-nowrap text-ink transition-colors hover:bg-page"
            : "rounded text-[13px] font-medium text-brand underline-offset-2 hover:underline",
        )}
      >
        <Upload className="size-3.5" /> Upload new trip
      </button>
      {open && <UploadDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function UploadDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [file, setFile] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const read = async (picked: File | undefined) => {
    if (!picked) return;
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      const encoded = await base64(picked);
      const r = await fetch("/api/uploads/preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ file: encoded }),
      });
      const body = await r.json();
      if (!r.ok) {
        setError(errorText(body, r.status));
        return;
      }
      const got = body as Preview;
      setFile(encoded);
      setPreview(got);
      setName(got.name ?? "");
      setStart(got.arrive_date);
    } catch {
      setError("Could not read that file.");
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    if (!file || !preview) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/uploads", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ file, arrive_date: start, name: name.trim() || null }),
      });
      const body = await r.json();
      if (!r.ok) {
        setError(errorText(body, r.status));
        setBusy(false);
        return;
      }
      // Stays busy: the button must not re-arm while the route transition is in flight.
      router.push(tripHref(body as Trip));
    } catch {
      setError("Could not reach the server.");
      setBusy(false);
    }
  };

  const span = preview
    ? Math.round((Date.parse(preview.depart_date) - Date.parse(preview.arrive_date)) / DAY_MS)
    : 0;
  const blocks = preview?.days.reduce((n, d) => n + d.blocks.length, 0) ?? 0;

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Upload new trip</DialogTitle>
          <DialogDescription>
            An .xlsx exported from a trip here, edited in Excel if you like. It becomes a new trip
            you own; costs and who it was shared with stay behind.
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4">
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={busy}
            onChange={(e) => read(e.target.files?.[0])}
            aria-label="Exported trip file"
            className="block w-full text-[13px] file:mr-3 file:rounded-full file:border-0 file:bg-page file:px-3 file:py-1.5 file:text-[12.5px] file:font-medium"
          />

          {busy && !preview && <p className="text-[13px] text-muted-foreground">Reading…</p>}

          {preview && (
            <>
              <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2">
                <span className="text-[13px] font-semibold">Name</span>
                <Input
                  value={name}
                  maxLength={120}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={preview.cities.join(" + ")}
                  aria-label="Trip name"
                />
                <span className="text-[13px] font-semibold">Starts</span>
                <div className="flex items-center gap-2">
                  <Input
                    type="date"
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                    aria-label="Start date"
                    className="w-40"
                  />
                  <span className="text-[12.5px] text-muted-foreground">
                    to {start ? shift(start, span) : "…"} · {span + 1} days
                  </span>
                </div>
              </div>

              <p className="text-[13px] text-muted-foreground">
                {preview.cities.join(" + ")} · {blocks} {blocks === 1 ? "block" : "blocks"} over{" "}
                {preview.days.length} {preview.days.length === 1 ? "day" : "days"}
              </p>

              <ul className="max-h-48 space-y-2 overflow-y-auto rounded-lg border border-hairline px-3 py-2.5">
                {preview.days.map((d) => (
                  <li key={d.day_index}>
                    <p className="font-mono text-[11px] text-faint uppercase">Day {d.day_index + 1}</p>
                    {d.blocks.map((b, i) => (
                      <p key={i} className="truncate text-[12.5px]">
                        <span className="mr-1.5 font-mono text-[11px] text-faint tabular-nums">
                          {b.start}–{b.end}
                        </span>
                        {b.name}
                      </p>
                    ))}
                  </li>
                ))}
              </ul>

              {preview.skipped.length > 0 && (
                <div className="rounded-lg border border-warn-border bg-warn-bg px-3 py-2.5">
                  <p className="text-[12.5px] font-medium text-warn">
                    {preview.skipped.length} {preview.skipped.length === 1 ? "row" : "rows"} left out
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {preview.skipped.map((s) => (
                      <li key={s.row} className="text-[12px] text-warn">
                        Row {s.row}: {s.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}

          {error && <p className="text-[12.5px] text-alert">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="lg" onClick={onClose}>
            Cancel
          </Button>
          <Button size="lg" disabled={!preview || !start || busy} onClick={create}>
            {busy && preview ? "Creating…" : "Create trip"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
