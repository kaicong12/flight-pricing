"use client";

// The API being down is not the same as a trip you cannot see, and it must not read as one.
// getJson throws on an unreachable or 5xx tp_api; a 404 or 403 still goes to not-found.

export default function AppError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto max-w-[620px] px-7 pt-30 text-center">
      <div className="mx-auto grid size-14 place-items-center rounded-[58%_42%_46%_54%_/_52%_56%_44%_48%] border border-alert/25 bg-alert-bg">
        <span className="size-1.5 rounded-full bg-alert" />
      </div>
      <h1 className="mt-6 text-[26px] font-semibold tracking-[-0.015em]">The planning API is not answering</h1>
      <p className="mt-2.5 text-[14.5px] leading-[1.55] text-muted-foreground">
        Nothing is lost — your trips are stored on the server. This is the connection to it, not your
        plan.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-6.5 inline-flex h-10.5 items-center rounded-full bg-ink px-5 text-[13.5px] font-medium text-primary-foreground transition-colors hover:bg-ink-hover outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        Try again
      </button>
    </main>
  );
}
