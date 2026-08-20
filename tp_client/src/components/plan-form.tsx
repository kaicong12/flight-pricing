"use client";

// The one screen: collect a city and dates, post them, then watch ingestion.

import { useState } from "react";

import { CityCombobox } from "@/components/city-combobox";
import { TripProgress } from "@/components/trip-progress";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorText, NOTE_TEXT, type CitySuggestion, type Trip } from "@/lib/api-types";

const FIELD = "h-11 rounded-lg border-input bg-white px-3 text-sm shadow-xs";

/** Empty strings would fail time parsing upstream, so they go as null. */
function orNull(value: string): string | null {
  return value.trim() === "" ? null : value;
}

export function PlanForm() {
  const [city, setCity] = useState<CitySuggestion | null>(null);
  const [arriveDate, setArriveDate] = useState("");
  const [arriveTime, setArriveTime] = useState("");
  const [departDate, setDepartDate] = useState("");
  const [departTime, setDepartTime] = useState("");
  const [extraDetails, setExtraDetails] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trip, setTrip] = useState<Trip | null>(null);

  const ready = city !== null && arriveDate !== "" && departDate !== "" && !submitting;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!city) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch("/api/plan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          city_place_id: city.place_id,
          arrive_date: arriveDate,
          arrive_time: orNull(arriveTime),
          depart_date: departDate,
          depart_time: orNull(departTime),
          extra_details: orNull(extraDetails),
        }),
      });
      const body = await r.json();
      if (!r.ok) {
        setError(errorText(body, r.status));
        return;
      }
      setTrip(body as Trip);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[520px] px-6 py-24">
      <h1 className="text-3xl font-bold tracking-tight">Plan a city trip</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        We read real travel videos to find places worth going to.
      </p>

      <form onSubmit={submit} className="mt-10 space-y-6">
        <div className="space-y-2">
          <Label htmlFor="city" className="text-sm font-semibold">
            Where are you going?
          </Label>
          <CityCombobox selected={city} onSelect={setCity} />
        </div>

        <div className="grid grid-cols-2 gap-5">
          <Leg
            label="Arriving"
            timeLabel="Flight lands"
            idPrefix="arrive"
            date={arriveDate}
            time={arriveTime}
            onDate={setArriveDate}
            onTime={setArriveTime}
          />
          <Leg
            label="Leaving"
            timeLabel="Flight departs"
            idPrefix="depart"
            date={departDate}
            time={departTime}
            onDate={setDepartDate}
            onTime={setDepartTime}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="extra" className="text-sm font-semibold">
            Anything we should know?
          </Label>
          <Textarea
            id="extra"
            rows={3}
            maxLength={500}
            value={extraDetails}
            onChange={(e) => setExtraDetails(e.target.value)}
            placeholder="We love food and design, want at least one proper sauna, not big on churches, happy to walk"
            className="rounded-lg border-input bg-white p-3 text-sm shadow-xs"
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <Button type="submit" disabled={!ready} className="h-11 w-full text-sm">
          {submitting ? "Finding places…" : "Find places"}
        </Button>
        <p className="text-center text-xs text-muted-foreground">
          We read real travel videos, so this takes a couple of minutes.
        </p>
      </form>

      {trip && (
        <section className="mt-10 space-y-3 rounded-lg border border-input bg-white p-4 text-sm">
          <p className="font-mono text-xs">trip_id: {trip.trip_id}</p>
          <p className="font-mono text-xs">
            ingest: {trip.ingest ? `${trip.ingest.run_id} — ${trip.ingest.status}` : "none (city already warm)"}
          </p>
          {trip.notes.map((n) => (
            <p key={n} className="text-xs text-muted-foreground">
              {NOTE_TEXT[n] ?? n}
            </p>
          ))}
          <TripProgress tripId={trip.trip_id} initialStatus={trip.ingest?.status ?? "done"} />
        </section>
      )}
    </div>
  );
}

type LegProps = {
  label: string;
  timeLabel: string;
  idPrefix: string;
  date: string;
  time: string;
  onDate: (v: string) => void;
  onTime: (v: string) => void;
};

function Leg({ label, timeLabel, idPrefix, date, time, onDate, onTime }: LegProps) {
  return (
    <div className="space-y-2">
      <Label htmlFor={`${idPrefix}-date`} className="text-sm font-semibold">
        {label}
      </Label>
      <Input
        id={`${idPrefix}-date`}
        type="date"
        value={date}
        onChange={(e) => onDate(e.target.value)}
        className={FIELD}
      />
      <Label htmlFor={`${idPrefix}-time`} className="text-xs font-normal text-muted-foreground">
        {timeLabel}
      </Label>
      <Input
        id={`${idPrefix}-time`}
        type="time"
        value={time}
        onChange={(e) => onTime(e.target.value)}
        className="h-9 rounded-lg border-input bg-white px-3 text-sm shadow-xs"
      />
    </div>
  );
}
