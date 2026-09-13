// Revoke the session row, then drop the cookie. Both, because the row is what actually ends it.

import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/cookies";
import { proxy } from "@/lib/tp-api";

export async function POST() {
  await proxy("/auth/session", { method: "DELETE" });
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}
