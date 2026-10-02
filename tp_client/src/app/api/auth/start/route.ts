// Step 1 of sign-in: send the browser to Google.

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
