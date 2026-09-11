// The signed-in user behind the session cookie. Server-only: the token is httpOnly, so it never
// reaches client JS.

import { cache } from "react";
import { cookies } from "next/headers";

import type { User } from "@/lib/api-types";
import { SESSION_COOKIE } from "@/lib/cookies";
import { getJson } from "@/lib/tp-api";

/** The signed-in user, or null. Memoized per render, so four pages cost one call. */
export const currentUser = cache(async (): Promise<User | null> => {
  if (!(await cookies()).get(SESSION_COOKIE)) return null;
  return getJson<User>("/auth/me");
});
