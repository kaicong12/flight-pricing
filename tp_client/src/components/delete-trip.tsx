"use client";

// Deleting is soft on the server, but there is no undo here, so it asks first.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errorText } from "@/lib/api-types";

export function DeleteTrip({ tripId, city }: { tripId: string; city: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setDeleting(true);
    setError(null);
    try {
      const r = await fetch(`/api/trips/${encodeURIComponent(tripId)}`, { method: "DELETE" });
      if (!r.ok) {
        setError(errorText(await r.json().catch(() => null), r.status));
        setDeleting(false);
        return;
      }
      // Stays deleting: the button must not re-arm while the route transition is in flight.
      router.push("/trips");
      router.refresh();
    } catch {
      setError("Could not reach the server.");
      setDeleting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase transition-colors hover:text-alert outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        Delete trip
      </button>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this {city} trip?</DialogTitle>
          <DialogDescription>
            It leaves your trips list. The days you have ordered are kept, but there is no undo in
            the app.
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-[13px] leading-[1.5] text-alert">{error}</p>}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />} disabled={deleting}>
            Keep it
          </DialogClose>
          <Button variant="destructive" onClick={remove} disabled={deleting}>
            {deleting ? "Deleting…" : "Delete trip"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
