"use client";

// A block the shortlist could never hold: a flight, a hotel night, a booked activity. The title is
// what the grid shows; the description is where the flight number or the check-in address goes.

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
import { Textarea } from "@/components/ui/textarea";
import type { CustomDraft } from "@/lib/plan-state";
import { MIN_DURATION, hhmm } from "@/lib/plan-types";
import { cn } from "@/lib/utils";

const DURATIONS = [30, 60, 90, 120, 180, 240, 360, 480, 720];
const TITLE_MAX = 120;
const DESCRIPTION_MAX = 1000;

function label(minutes: number): string {
  return minutes < 60 ? `${minutes}m` : `${minutes / 60}h`.replace(".5", "½");
}

/** Mounted only while open, so the caller's `key` is what resets it rather than an effect. */
export function CustomBlockDialog({
  startMin,
  room,
  editing,
  onClose,
  onSubmit,
}: {
  /** The clicked half hour, or the block's own start when editing. */
  startMin: number;
  /** Minutes left before the flight window closes, so no chip offers a block that cannot be saved. */
  room: number;
  editing: (CustomDraft & { durationMin: number }) | null;
  onClose: () => void;
  onSubmit: (draft: CustomDraft, durationMin: number) => void;
}) {
  const [title, setTitle] = useState(editing?.title ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [durationMin, setDurationMin] = useState(
    editing?.durationMin ?? Math.min(60, Math.max(MIN_DURATION, room)),
  );

  const trimmed = title.trim();
  const fits = DURATIONS.filter((m) => m <= room);

  const save = () => {
    if (!trimmed) return;
    onSubmit({ title: trimmed, description: description.trim() || null }, durationMin);
    onClose();
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit block" : `Add a block at ${hhmm(startMin)}`}</DialogTitle>
          <DialogDescription>
            A flight, a stay, anything booked. It is yours — nothing checks it against opening hours.
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4">
          <Input
            autoFocus
            value={title}
            maxLength={TITLE_MAX}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            placeholder="Flight SQ 3116 to Oslo"
            aria-label="What is this block"
          />

          <Textarea
            value={description}
            maxLength={DESCRIPTION_MAX}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Booking reference, terminal, address, who to ask for"
            aria-label="Details"
            className="min-h-20 text-[13.5px]"
          />

          {!editing && (
            <fieldset className="space-y-2">
              <legend className="text-[13px] font-semibold">How long?</legend>
              <div className="flex flex-wrap gap-1.5">
                {fits.map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={durationMin === m}
                    onClick={() => setDurationMin(m)}
                    className={cn(
                      "flex h-7 items-center rounded-full px-3 text-[12.5px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      durationMin === m
                        ? "bg-ink text-primary-foreground"
                        : "bg-page text-muted-foreground hover:text-ink",
                    )}
                  >
                    {label(m)}
                  </button>
                ))}
              </div>
            </fieldset>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="lg" onClick={onClose}>
            Cancel
          </Button>
          <Button size="lg" disabled={!trimmed} onClick={save}>
            {editing ? "Save" : "Add to day"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
