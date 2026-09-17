// Covers this segment and /plan below it. Deliberately does not say which of the two it is: tp_api
// answers 404 for a trip you cannot see so that trip ids stay unguessable, and saying "not shared
// with you" here would give that back.

import Link from "next/link";

export default function TripNotFound() {
  return (
    <main className="mx-auto max-w-[620px] px-7 pt-30 text-center">
      <div className="mx-auto grid size-14 place-items-center rounded-[58%_42%_46%_54%_/_52%_56%_44%_48%] border border-border surface">
        <span className="size-5 rounded-[999px_6px_999px_6px] bg-linear-135 from-[#cfc6ae] to-[#c8b9b0]" />
      </div>
      <h1 className="mt-6 text-[26px] font-semibold tracking-[-0.015em]">This trip is not available</h1>
      <p className="mt-2.5 text-[14.5px] leading-[1.55] text-muted-foreground">
        Either it does not exist, or it has not been shared with you. A trip link on its own grants
        nothing — ask whoever planned it to add you.
      </p>
      <Link
        href="/trips"
        className="mt-6.5 inline-flex h-10.5 items-center rounded-full bg-ink px-5 text-[13.5px] font-medium text-primary-foreground transition-colors hover:bg-ink-hover outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        Your trips
      </Link>
    </main>
  );
}
