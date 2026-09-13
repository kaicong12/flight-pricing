// The one screen reachable without a session.

import { redirect } from "next/navigation";

import { currentUser } from "@/lib/session";

export const metadata = { title: "Sign in" };
export const dynamic = "force-dynamic";

// Google's own error page handles a misconfigured client, so these are the ones that reach us.
const REASONS: Record<string, string> = {
  access_denied: "You cancelled the Google sign-in.",
  bad_state: "That sign-in link had gone stale. Try again.",
  no_code: "Google did not send a sign-in code back. Try again.",
  exchange_failed: "We could not complete the sign-in. Try again.",
  not_configured: "Google sign-in is not configured on the server.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  if (await currentUser()) redirect("/trips");
  const { error } = await searchParams;
  const reason = typeof error === "string" ? (REASONS[error] ?? REASONS.exchange_failed) : null;

  return (
    <div className="grid min-h-dvh place-items-center bg-page px-6">
      <main className="w-full max-w-[380px]">
        <div className="flex items-center gap-2.5">
          <span className="size-5.5 rounded-[999px_4px_999px_4px] bg-linear-135 from-ok to-brand" />
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Trip Planner</span>
        </div>
        <h1 className="mt-7 text-3xl font-semibold tracking-[-0.015em]">Plan a city trip</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          We read real travel videos to find places worth going to. Sign in to keep your trips.
        </p>

        {reason ? (
          <p role="alert" className="mt-6 rounded-lg bg-destructive/10 px-3.5 py-2.5 text-[13.5px] text-destructive">
            {reason}
          </p>
        ) : null}

        <a
          href="/api/auth/start"
          className="mt-7 flex h-10 items-center justify-center gap-2.5 rounded-full bg-ink px-5 text-[13.5px] font-medium text-white transition-colors hover:bg-ink/90 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <GoogleMark />
          Continue with Google
        </a>
      </main>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 18 18" className="size-4">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.34A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.97 10.71a5.4 5.4 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.09l3.01-2.34Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.96l3.01 2.33C4.68 5.17 6.66 3.58 9 3.58Z" />
    </svg>
  );
}
