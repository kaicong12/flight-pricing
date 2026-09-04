"use client";

// Collects a city and dates, posts them, then hands off to /trip/[tripId] for the watching.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { CityCombobox } from "@/components/city-combobox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorText, type CitySuggestion, type Trip } from "@/lib/api-types";
import { tripHref } from "@/lib/trips";

const FIELD = "h-11 rounded-[13px] border-input px-3.5 text-sm";
const LABEL = "text-[13px] font-semibold";

const STEPS = [
  "We search YouTube and RedNote for this city, in English and the local language.",
  "Gemini pulls the place names out of transcripts and note bodies.",
  "Each name resolves to a Google place_id, so two sources naming one venue count as one place.",
  "You get a shortlist ranked by independent mentions. You choose the order.",
];

// Routes API answers ROUTE_NOT_FOUND for transit beyond ~100 days, so the caveat is knowable
// from the date the user just typed — before they commit, not after.
const TRANSIT_HORIZON_DAYS = 100;

/** Empty strings would fail time parsing upstream, so they go as null. */
function orNull(value: string): string | null {
  return value.trim() === "" ? null : value;
}

function pastTransitHorizon(date: string): boolean {
  if (date === "") return false;
  const days = (Date.parse(`${date}T00:00:00`) - Date.now()) / 86_400_000;
  return days > TRANSIT_HORIZON_DAYS;
}

export function PlanForm() {
  const router = useRouter();
  const [city, setCity] = useState<CitySuggestion | null>(null);
  const [name, setName] = useState("");
  const [arriveDate, setArriveDate] = useState("");
  const [arriveTime, setArriveTime] = useState("");
  const [departDate, setDepartDate] = useState("");
  const [departTime, setDepartTime] = useState("");
  const [extraDetails, setExtraDetails] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
          name: orNull(name),
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
        setSubmitting(false);
        return;
      }
      // Stays submitting: the button must not re-arm while the route transition is in flight.
      router.push(tripHref(body as Trip));
    } catch {
      setError("Could not reach the server.");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto grid w-full max-w-[1060px] items-start gap-12 px-7 pt-14 pb-24 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div>
        <h1 className="text-[32px] font-semibold tracking-[-0.015em]">Plan a city trip</h1>
        <p className="mt-2.5 text-[14.5px] text-muted-foreground">
          We read real travel videos to find places worth going to.
        </p>

        <form
          onSubmit={submit}
          className="mt-8 rounded-card border border-border surface px-7 pt-6.5 pb-7 shadow-card"
        >
          <Label htmlFor="city" className={LABEL}>
            Where are you going?
          </Label>
          <div className="mt-2">
            <CityCombobox selected={city} onSelect={setCity} />
          </div>

          <div className="mt-6">
            <Label htmlFor="name" className={LABEL}>
              Call it something
            </Label>
            <Input
              id="name"
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={city ? `${city.main_text ?? city.description} trip` : "Optional"}
              className="mt-2"
            />
            <p className="mt-1.5 text-xs text-faint">Optional — we will use the city name.</p>
          </div>

          <div className="mt-6 grid gap-5 sm:grid-cols-2">
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

          <div className="mt-6">
            <Label htmlFor="extra" className={LABEL}>
              Anything we should know?
            </Label>
            <Textarea
              id="extra"
              rows={3}
              maxLength={500}
              value={extraDetails}
              onChange={(e) => setExtraDetails(e.target.value)}
              placeholder="We love food and design, want at least one proper sauna, not big on churches, happy to walk"
              className="mt-2 min-h-22 rounded-[13px] border-input p-3.5 text-sm leading-[1.5]"
            />
            <p className="mt-1.5 text-xs text-faint">One sentence is enough. 500 characters max.</p>
          </div>

          {pastTransitHorizon(arriveDate) && (
            <div className="mt-6.5 flex items-center gap-3.5 rounded-[13px] border border-warn-border bg-warn-bg px-4 py-3.5">
              <span className="size-1.5 shrink-0 rounded-full bg-warn" />
              <p className="text-[13px] leading-[1.5] text-warn">
                That is past the transit routing horizon, so this plan will use walking times only.
                We will re-check nearer the date.
              </p>
            </div>
          )}

          {error && (
            <p role="alert" className="mt-6 text-sm text-destructive">
              {error}
            </p>
          )}

          <Button type="submit" disabled={!ready} className="mt-5.5 h-11.5 w-full rounded-full text-sm hover:bg-ink-hover">
            {submitting ? "Finding places…" : "Find places"}
          </Button>
          <p className="mt-3 text-center text-xs text-faint">
            We read real travel videos, so this takes a couple of minutes.
          </p>
        </form>
      </div>

      <aside className="border-border pl-0 lg:sticky lg:top-23 lg:border-l lg:pl-6">
        <h2 className="font-mono text-[11px] tracking-[0.06em] text-faint uppercase">
          What happens next
        </h2>
        <ol className="mt-4 grid gap-4.5">
          {STEPS.map((text, i) => (
            <li key={text} className="grid grid-cols-[22px_minmax(0,1fr)] items-start gap-3">
              <span className="grid size-5.5 place-items-center rounded-full bg-page font-mono text-[11px] text-muted-foreground">
                {i + 1}
              </span>
              <span className="text-[13px] leading-[1.55] text-ink-soft">{text}</span>
            </li>
          ))}
        </ol>
      </aside>
    </main>
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
    <div>
      <Label htmlFor={`${idPrefix}-date`} className={LABEL}>
        {label}
      </Label>
      <div className="mt-2 flex gap-2.5">
        <Input
          id={`${idPrefix}-date`}
          type="date"
          value={date}
          onChange={(e) => onDate(e.target.value)}
          className={FIELD}
        />
        <Input
          type="time"
          aria-label={timeLabel}
          value={time}
          onChange={(e) => onTime(e.target.value)}
          className={`${FIELD} w-auto shrink-0 px-2.5 font-mono`}
        />
      </div>
      <p className="mt-1.5 text-xs text-faint">{timeLabel}</p>
    </div>
  );
}
