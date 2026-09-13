// Step 2 of sign-in: Google's redirect lands here. tp_api does the exchange — it holds the client
// secret and the database — and this only turns the result into a cookie.

import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import { SESSION_COOKIE, STATE_COOKIE } from "@/lib/cookies";
import type { User } from "@/lib/api-types";
import { postAnon } from "@/lib/tp-api";

const SESSION_MAX_AGE = 60 * 60 * 24 * 30;

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const jar = await cookies();
  const expected = jar.get(STATE_COOKIE)?.value;
  jar.delete(STATE_COOKIE);

  // Google renders its own error page for a bad client or redirect_uri, so what reaches here is
  // either a code or the user having pressed Deny.
  const error = params.get("error");
  if (error) redirect(`/login?error=${encodeURIComponent(error)}`);

  const code = params.get("code");
  if (!code) redirect("/login?error=no_code");
  if (!expected || params.get("state") !== expected) redirect("/login?error=bad_state");

  const session = await postAnon<{ token: string; user: User }>("/auth/google", { code });
  if (!session) redirect("/login?error=exchange_failed");

  jar.set(SESSION_COOKIE, session.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  redirect("/trips");
}
