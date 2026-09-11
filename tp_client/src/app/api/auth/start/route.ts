// Step 1 of sign-in: send the browser to Google.
//
// tp_api builds the URL, because the redirect_uri has to match byte-for-byte in both the
// authorization request and the token exchange, and tp_api owns the exchange. The state is ours: it
// pairs with the cookie set here.

import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import { STATE_COOKIE } from "@/lib/cookies";
import { getJson } from "@/lib/tp-api";

export async function GET() {
  const state = crypto.randomUUID();
  const target = await getJson<{ url: string }>(`/auth/url?state=${state}`);
  if (!target) redirect("/login?error=not_configured");

  (await cookies()).set(STATE_COOKIE, state, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 600,
  });
  redirect(target.url);
}
